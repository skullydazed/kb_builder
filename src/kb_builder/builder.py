#!/usr/bin/env python
# -*- coding: utf-8 -*-

# kb_builder builts keyboard plate and case CAD files using JSON input.
#
# Copyright (C) 2015  Will Stevens (swill)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Some notes that have helped skullydazed make sense of this code as an outsider
#
# * Kerf is used only to change the line position. Positioning center should
#   be done without taking kerf into account- or, in some cases, undoing the
#   kerf adjustment.
# * Sometimes FreeCAD wants things done in a certain order. I haven't been able
#   to determine why. If you have FreeCAD throwing obscure errors at you try
#   changing the order of operations.
import hashlib
import hjson
import logging
import math
import sys

from functions import rotate_points
from os import makedirs
from os.path import exists

sys.path.append('/usr/lib/freecad/lib')  # Setup the import environment for FreeCAD
import FreeCAD
import cadquery
import importDXF
import importSVG
import Mesh
import Part


log = logging.getLogger()

# Custom log levels
CUT_SWITCH = 9
CENTER_MOVE = 8

logging.addLevelName(CUT_SWITCH, 'cut_switch')
logging.addLevelName(CENTER_MOVE, 'center_move')

# Constants
STABILIZERS = {
    # size: (width_between_center, switch_offset)
    2: (11.95, 0),
    3: (19.05, 0),
    4: (28.575, 0),
    4.5: (34.671, 0),
    5.5: (42.8625, 0),
    6: (47.625, 9.525),
    6.25: (50, 0),
    6.5: (52.38, 0),
    7: (57.15, 0),
    8: (66.675, 0),
    9: (66.675, 0),
    10: (66.675, 0)
}


class KeyboardCase(object):
    def __init__(self, keyboard_layout, formats=None):
        # User settable things
        self.name = None
        self.case = {'type': None}
        self.case_type = None
        self.corner_type = None
        self.corners = 0
        self.formats = formats if formats else ['dxf']
        self.feet = None
        self.foot_hole_diameter = 3
        self.foot_hole_square = 9
        self.kerf = 0
        self.keyboard_layout = keyboard_layout
        self.holes = []
        self.screw = {'count': 4, 'radius': 2}
        self.layer_screw = self.screw.copy()
        self.stab_type = 'cherry'
        self.switch_type = 'mx'
        self.key_spacing = 19.05
        self.usb = {
            'inner_width': 10,
            'outer_width': 10,
            'height': 5,
            'offset': 0
        }
        self.x_pad = 0
        self.x_pcb_pad = 0
        self.y_pad = 0
        self.y_pcb_pad = 0

        # Plate state info
        self.plate = None
        self.UOM = "mm"
        self.exports = {}
        self.grow_y = 0
        self.grow_x = 0
        self.height = 0
        self.inside_height = 0
        self.inside_width = 0
        self.layers = {'switch': {}}
        self.layout = []
        self.origin = (0,0)
        self.width = 0
        self.x_off = 0
        self.x_holes = 0
        self.y_holes = 0

        # Determine the size of each key
        self.parse_layout()

    def create_bottom_layer(self, layer='bottom'):
        """Returns a copy of the bottom layer ready to export.
        """
        log.debug("create_bottom_layer(layer='%s')" % layer)
        self.init_plate(layer)

        if self.feet:
            self.cut_feet_holes()

        return self.plate.cutThruAll()

    def create_middle_layer(self, layer='closed'):
        """Returns a copy of the middle layer ready to export.

        We stash nifty things like the feet in this layer.
        """
        log.debug("create_middle_layer(layer='%s')" % layer)
        inside_width = self.inside_width-self.kerf*2
        inside_height = self.inside_height-self.kerf*2
        self.init_plate(layer)
        outline_points = [
            (inside_width/2, inside_height/2),
            (-inside_width/2, inside_height/2),
            (-inside_width/2, -inside_height/2),
            (inside_width/2, -inside_height/2),
            (inside_width/2, inside_height/2)
        ]

        self.plate = self.plate.polyline(outline_points)  # Cut the internal outline

        if self.feet:
            self.draw_feet()

        self.plate = self.plate.cutThruAll()

        return self.plate

    def create_switch_layer(self, layer):
        """Returns a copy of one of the switch based layers ready to export.

        The switch based layers are `switch`, `reinforcing`, and `top`.
        """
        log.debug("create_switch_layer(layer='%s')" % layer)
        prev_width = None
        prev_y_off = 0

        self.init_plate(layer)
        self.center(-self.width/2, -self.height/2) # move to top left of the plate

        for r, row in enumerate(self.layout):
            for k, key in enumerate(row):
                x, y, kx = 0, 0, 0
                if 'x' in key:
                    x = key['x'] * self.key_spacing
                    kx = x

                if 'y' in key and k == 0:
                    y = key['y'] * self.key_spacing

                if r == 0 and k == 0: # handle placement of the first key in first row
                    self.center((key['w'] * self.key_spacing / 2), (self.key_spacing / 2))
                    x += (self.x_pad+self.x_pcb_pad)
                    y += (self.y_pad+self.y_pcb_pad)
                    # set x_off negative since the 'cut_switch' will append 'x' and we need to account for initial spacing
                    self.x_off = -(x - (self.key_spacing/2 + key['w']*self.key_spacing/2) - kx)
                elif k == 0: # handle changing rows
                    self.center(-self.x_off, self.key_spacing) # move to the next row
                    self.x_off = 0 # reset back to the left side of the plate
                    x += self.key_spacing/2 + key['w']*self.key_spacing/2
                else: # handle all other keys
                    x += prev_width*self.key_spacing/2 + key['w']*self.key_spacing/2

                if prev_y_off != 0: # prev_y_off != 0
                    y += -prev_y_off
                    prev_y_off = 0

                if 'h' in key and key['h'] > 1: # deal with vertical keys
                    prev_y_off = key['h']*self.key_spacing/2 - self.key_spacing/2
                    y += prev_y_off

                # Cut the switch hole
                self.cut_switch((x, y), key, layer)
                prev_width = key['w']

        self.recenter()
        return self.plate.cutThruAll()

    def draw_feet(self):
        """Draw the feet on a layer.
        """
        log.debug("cut_feet()")
        hole_radius = 3
        small_foot_offset = 27
        x_offset, y_offset = self.feet.get('draw_offset', [0,0])
        foot_width = self.feet['width'] / 2
        left_side = -foot_width + x_offset
        right_side = foot_width + x_offset
        screw_offset = self.feet.get('screw_offset', foot_width - 3)
        left_hole = -screw_offset + x_offset
        right_hole = screw_offset + x_offset

        small_foot = [
            (left_side+1,10),
            (right_side-1,10),
            (right_side+5,4),
            (right_side+5,-4),
            (right_side-1,-10),
            (left_side+1,-10),
            (left_side-5,-4),
            (left_side-5,4),
            (left_side+1,10)
        ]
        big_foot = [
            (left_side,15),
            (right_side,15),
            (right_side+8,7),
            (right_side+8,-7),
            (right_side,-15),
            (left_side,-15),
            (left_side-8,-7),
            (left_side-8,7),
            (left_side,15)
        ]

        # Draw the big foot
        self.plate = self.plate.polyline(big_foot)
        self.plate = self.plate.center(left_hole, 0).circle((hole_radius)-self.kerf).center(-left_hole, 0)
        self.plate = self.plate.center(right_hole, 0).circle((hole_radius)-self.kerf).center(-right_hole, 0)

        # Draw the top small foot
        self.plate = self.plate.center(0, small_foot_offset).polyline(small_foot).center(0, -small_foot_offset)
        self.plate = self.plate.center(left_hole, small_foot_offset).circle((hole_radius)-self.kerf).center(-left_hole, -small_foot_offset)
        self.plate = self.plate.center(right_hole, small_foot_offset).circle((hole_radius)-self.kerf).center(-right_hole, -small_foot_offset)

        # Draw the bottom small foot
        self.plate = self.plate.center(0, -small_foot_offset).polyline(small_foot).center(0, small_foot_offset)
        self.plate = self.plate.center(left_hole, -small_foot_offset).circle((hole_radius)-self.kerf).center(-left_hole, small_foot_offset)
        self.plate = self.plate.center(right_hole, -small_foot_offset).circle((hole_radius)-self.kerf).center(-right_hole, small_foot_offset)

        return self.plate

    def cut_feet_holes(self):
        """Cut the mounting points for the feet.
        """
        log.debug("cut_feet_holes()")

        hole_radius = 1.5
        foot_width = self.feet['width'] / 2
        screw_offset = self.feet.get('screw_offset', foot_width - 3)
        top_foot_x, top_foot_y = self.feet.get('top_foot', [0,-25])
        bottom_foot_x, bottom_foot_y = self.feet.get('bottom_foot', [0,25])
        left_hole = -screw_offset + top_foot_x
        right_hole = screw_offset + bottom_foot_x

        self.plate = self.plate.center(left_hole, top_foot_y).circle((hole_radius)-self.kerf).center(-left_hole, -top_foot_y)
        self.plate = self.plate.center(right_hole, top_foot_y).circle((hole_radius)-self.kerf).center(-right_hole, -top_foot_y)
        self.plate = self.plate.center(left_hole, bottom_foot_y).circle((hole_radius)-self.kerf).center(-left_hole, -bottom_foot_y)
        self.plate = self.plate.center(right_hole, bottom_foot_y).circle((hole_radius)-self.kerf).center(-right_hole, -bottom_foot_y)

        return self.plate.cutThruAll()

    def cut_usb_hole(self, layer):
        """Cut the opening that allows for the USB hole.
        """
        log.debug("cut_usb_hole(layer='%s')" % (layer))
        extra_distance = 0
        oversize = self.layers[layer].get('oversize', 0)
        top_line_y = -(self.height + self.kerf*2 + oversize) / 2
        bottom_line_y = -(self.inside_height - self.kerf*2) / 2

        if oversize > 0:
            # Calculate how wide the top line should be to keep the cutout
            # angle the same on oversized plates as normal plates
            lower_point = ((self.usb['inner_width']-self.kerf)/2, bottom_line_y)
            upper_point = ((self.usb['outer_width']+self.kerf)/2, top_line_y)
            xDiff = upper_point[0] - lower_point[0]
            yDiff = upper_point[1] - lower_point[1]
            radian = math.atan2(yDiff, xDiff)
            extra_distance = math.tan(radian) * (oversize/4)

        top_line = (self.usb['outer_width'] + self.kerf) / 2
        top_line_x_left = -top_line + self.usb['offset'] + extra_distance
        top_line_x_right = top_line + self.usb['offset'] - extra_distance
        bottom_line = (self.usb['inner_width'] - self.kerf) / 2
        bottom_line_x_left = -bottom_line + self.usb['offset']
        bottom_line_x_right = bottom_line + self.usb['offset']

        # Draw the isosceles trapezoid for the USB cutout
        points = [
            (top_line_x_left, top_line_y),
            (top_line_x_right, top_line_y),
            (bottom_line_x_right, bottom_line_y),
            (bottom_line_x_left, bottom_line_y),
            (top_line_x_left, top_line_y)
        ]
        self.plate = self.plate.polyline(points)

        if layer == 'bottom':
            # Draw a rectangle to accommodate the USB connector
            points = [
                (bottom_line_x_left, bottom_line_y),
                (bottom_line_x_right, bottom_line_y),
                (bottom_line_x_right, bottom_line_y + self.usb['height'] + self.kerf*2),
                (bottom_line_x_left, bottom_line_y + self.usb['height'] + self.kerf*2),
                (bottom_line_x_left, bottom_line_y)
            ]
            self.plate = self.plate.polyline(points)

        self.plate = self.plate.cutThruAll()
        return self.plate

    def cut_plate_polygons(self, layer):
        """Cut any polygons specified for this layer.
        """
        log.debug("cut_plate_polygons(layer='%s')" % (layer))
        #self.center(-self.width/2 + self.kerf, -self.height/2 + self.kerf) # move to top left of the plate

        for polygon in self.layers[layer]['polygons']:
            self.plate = self.plate.polyline(polygon)

        self.plate = self.plate.cutThruAll()
        #self.center(self.width/2 - self.kerf, self.height/2 - self.kerf) # move to center of the plate

    def cut_plate_holes(self, layer):
        """Cut any holes specified for this layer.
        """
        log.debug("cut_plate_holes(layer='%s')" % (layer))
        self.center(-self.width/2 + self.kerf, -self.height/2 + self.kerf) # move to top left of the plate

        for hole in self.layers[layer]['holes']:
            x, y, radius = hole
            log.debug('Cutting %f wide hole at %s,%s', radius*2, x, y)
            self.plate = self.plate.center(x, y).circle((radius)-self.kerf).center(-x, -y)

        self.center(self.width/2 - self.kerf, self.height/2 - self.kerf) # move to center of the plate

        return self.plate.cutThruAll()

    def parse_layout(self):
        """Parse the supplied layout to determine size and populate the properties of each key.
        """
        log.debug('parse_layout()')
        layout_width = 0
        layout_height = 0
        key_desc = False # track if current is not a key and only describes the next key
        for row in self.keyboard_layout:
            if isinstance(row, dict):
                # This row describes features about the whole keyboard.
                if 'name' in row:
                    self.name = row['name']

                if 'case_type' in row:
                    self.case_type = row['case_type']
                    if self.case_type == 'poker' and not ('screw' in row and 'radius' in row['screw'] and row['screw']['radius'] > 0):
                        log.warning('screw.size not set, defaulting to %s' % self.layer_screw['radius'])

                    elif self.case_type == 'sandwich':
                        if 'screw' not in row:
                            log.warning('No screw setting, defaulting to %s screws with a radius of %s' % (self.layer_screw['count'], self.layer_screw['radius']))
                        elif 'radius' not in row['screw'] or row['screw']['radius'] <= 0:
                            log.warning('screw.radius not set, defaulting to 2!')
                        elif 'count' not in row['screw'] or row['screw']['count'] < 4:
                            log.error('Need at least 4 screws for a sandwich case! screw.count: %d < 4', self.layer_screw['count'])

                    elif self.case_type:
                        log.error('Unknown case type: %s', self.case_type)

                if 'corner_type' in row:
                    if row['corner_type'] in ('round', 'bevel'):
                        self.corner_type = row['corner_type']
                    else:
                        log.error('Unknown corner_type %s, defaulting to %s!', row['corner_type'], self.corner_type)

                if 'corner_radius' in row:
                    self.corners = float(row['corner_radius'])

                if 'feet' in row:
                    self.feet = row['feet']

                if 'kerf' in row:
                    self.kerf = float(row['kerf'])

                if 'key_spacing' in row:
                    self.key_spacing = float(row['key_spacing'])

                if 'padding' in row:
                    self.x_pad = float(row['padding'][0])
                    self.y_pad = float(row['padding'][1])

                if 'pcb_padding' in row:
                    self.x_pcb_pad = float(row['pcb_padding'][0]) / 2
                    self.y_pcb_pad = float(row['pcb_padding'][1]) / 2

                if 'usb' in row:
                    self.usb = row['usb']
                    self.usb = {
                        'inner_width': float(row['usb']['inner_width'] if 'inner_width' in row['usb'] else 10),
                        'outer_width': float(row['usb']['outer_width'] if 'outer_width' in row['usb'] else 15),
                        'height': float(row['usb']['height'] if 'height' in row['usb'] else 5),
                        'offset': float(row['usb']['offset'] if 'offset' in row['usb'] else 0)
                    }

                if 'screw' in row:
                    if 'count' in row['screw'] and isinstance(row['screw']['count'], int):
                        self.screw['count'] = row['screw']['count']
                    else:
                        log.warning('Invalid screw.count! Defaulting to %s' % self.layer_screw['count'])
                    if 'radius' in row['screw'] and isinstance(row['screw']['radius'], (int, float)):
                        self.screw['radius'] = row['screw']['radius']
                    else:
                        log.warning('Invalid screw.radius! Defaulting to %s' % self.layer_screw['radius'])

                if 'stabilizer' in row:
                    if row['stabilizer'] in ('cherry', 'costar', 'cherry-costar', 'matias', 'alps'):
                        self.stab_type = row['stabilizer']
                    else:
                        log.error('Unknown stabilizer type %s, defaulting to "cherry"!', row['stabilizer'])
                        self.stab_type = 'cherry'

                if 'switch' in row:
                    if row['switch'] in ('mx', 'alpsmx', 'mx-open', 'mx-open-rotatable', 'alps'):
                        self.switch_type = row['switch']
                    else:
                        log.error('Unknown switch type %s, defaulting to mx!', row['switch'])
                        self.switch_type = 'mx'

                if 'layers' in row:
                    self.layers = row['layers']

                if 'grow_x' in row and isinstance(row['grow_x'], (int, float)):
                    self.grow_x = row['grow_x']/2

                if 'grow_y' in row and isinstance(row['grow_y'], (int, float)):
                    self.grow_y = row['grow_y']/2

            elif isinstance(row, list):
                # This row is a list of keys that we process
                row_width = 0
                row_height = 0
                row_layout = []
                for k in row:
                    key = {}
                    if isinstance(k, dict): # descibes the next key
                        key = k
                        if 'w' not in key:
                            key['w'] = 1
                        if 'h' not in key:
                            key['h'] = 1
                        row_layout.append(key)
                        key_desc = True
                    else: # is just a standard key (we know its a single unit key)
                        if not key_desc: # only handle if it was not already handled as a key_desc
                            key['w'] = 1
                            key['h'] = 1
                            row_layout.append(key)
                        key_desc = False
                    if 'w' in key:
                        row_width += key['w']
                    if 'x' in key:
                        row_width += key['x'] # offsets count towards total row width
                    if 'y' in key:
                        row_height = key['y']
                self.layout.append(row_layout)
                if row_width > layout_width:
                    layout_width = row_width
                layout_height += self.key_spacing + row_height*self.key_spacing
            else:
                log.warn('Unknown row type: %s', type(row))

        # Set some values based on the layout we parsed above
        if not self.name:
            export_basename = hjson.dumps(self.layout, sort_keys=True)
            self.name = hashlib.sha1(export_basename).hexdigest()

        self.width = layout_width*self.key_spacing + 2*(self.x_pad+self.x_pcb_pad)
        self.height = layout_height + 2*(self.y_pad+self.y_pcb_pad)
        self.inside_height = self.height-self.y_pad*2-self.kerf*2
        self.inside_width = self.width-self.x_pad*2-self.kerf*2
        self.horizontal_edge = self.width / 2
        self.vertical_edge = self.height / 2

    def init_plate(self, layer):
        """Return a basic plate with the features that are common to all layers.
        """
        log.debug("init_plate(layer='%s')" % layer)

        # Basic plate info
        inset = self.layers[layer].get('inset', False)
        oversize = self.layers[layer].get('oversize', 0)
        width = self.inside_width-self.kerf*2+oversize if inset else self.width+self.kerf*2+oversize
        height = self.inside_height-self.kerf*2+oversize if inset else self.height+self.kerf*2+oversize

        self.plate = cadquery.Workplane("front").box(width, height, self.layers[layer].get('thickness', 1.5))

        # Check to see if this layer overrides any screw defaults
        self.layer_screw = self.screw.copy()  # Reset this in case a previous layer changed something
        if 'screw' in self.layers[layer]:
            if 'count' in self.layers[layer]['screw']:
                self.layer_screw['count'] = self.layers[layer]['screw']['count']
            if 'radius' in self.layers[layer]['screw']:
                self.layer_screw['radius'] = self.layers[layer]['screw']['radius']

        # Cut the corners if necessary
        if not inset and self.corners > 0 and self.corner_type == 'round':
            self.plate = self.plate.edges("|Z").fillet(self.corners)

        self.plate = self.plate.faces("<Z").workplane()

        if not inset and self.corners > 0:
            if self.corner_type == 'bevel':
                # Lower right corner
                points = (
                    (self.horizontal_edge + self.kerf, self.vertical_edge + self.kerf - self.corners), (self.horizontal_edge + self.kerf, self.vertical_edge + self.kerf),
                    (self.horizontal_edge + self.kerf - self.corners, self.vertical_edge + self.kerf), (self.horizontal_edge + self.kerf, self.vertical_edge + self.kerf - self.corners),
                )
                self.plate = self.plate.polyline(points)
                # Lower left corner
                points = (
                    (-self.horizontal_edge - self.kerf, self.vertical_edge + self.kerf - self.corners), (-self.horizontal_edge - self.kerf, self.vertical_edge + self.kerf),
                    (-self.horizontal_edge - self.kerf + self.corners, self.vertical_edge + self.kerf), (-self.horizontal_edge - self.kerf, self.vertical_edge + self.kerf - self.corners),
                )
                self.plate = self.plate.polyline(points)
                # Upper right corner
                points = (
                    (self.horizontal_edge + self.kerf, -self.vertical_edge - self.kerf + self.corners), (self.horizontal_edge + self.kerf, -self.vertical_edge - self.kerf),
                    (self.horizontal_edge + self.kerf - self.corners, -self.vertical_edge - self.kerf), (self.horizontal_edge + self.kerf, -self.vertical_edge - self.kerf + self.corners),
                )
                self.plate = self.plate.polyline(points)
                # Upper left corner
                points = (
                    (-self.horizontal_edge - self.kerf, -self.vertical_edge - self.kerf + self.corners), (-self.horizontal_edge - self.kerf, -self.vertical_edge - self.kerf),
                    (-self.horizontal_edge - self.kerf + self.corners, -self.vertical_edge - self.kerf), (-self.horizontal_edge - self.kerf, -self.vertical_edge - self.kerf + self.corners),
                )
                self.plate = self.plate.polyline(points)
            elif self.corner_type != 'round':
                log.error('Unknown corner type %s!', self.corner_type)

        # Cut the mount holes in the plate
        if inset or not self.case_type or self.case_type == 'reinforcing':
            pass
        elif self.case_type == 'poker':
            hole_points = [(-139,9.2), (-117.3,-19.4), (-14.3,0), (48,37.9), (117.55,-19.4), (139,9.2)] # holes
            rect_center = (self.width/2) - (3.5/2)
            rect_points = [(rect_center,9.2), (-rect_center,9.2)] # edge slots
            rect_size = (3.5-self.kerf, 5-self.kerf) # edge slot cutout to edge
            for c in hole_points:
                self.plate = self.plate.center(c[0], c[1]).hole(self.layer_screw['radius'] - self.kerf).center(-c[0],-c[1])
            for c in rect_points:
                self.plate = self.plate.center(c[0], c[1]).rect(*rect_size).center(-c[0],-c[1])
        elif self.case_type == 'sandwich':
            self.plate = self.center(-self.width/2 + self.kerf, -self.height/2 + self.kerf) # move to top left of the plate
            if self.layer_screw['count'] >= 4:
                self.layout_sandwich_holes()
                radius = self.layer_screw['radius'] - self.kerf
                x_gap = (self.width - 4*self.screw['radius'] + 1) / (self.x_holes + 1)
                y_gap = (self.height - 4*self.screw['radius'] + 1) / (self.y_holes + 1)
                hole_distance = self.screw['radius']*2 - .5 - self.kerf  # FIXME: Grab this from the keyboard properties if given
                self.plate = self.plate.center(hole_distance, hole_distance)
                for i in range(self.x_holes + 1):
                    self.plate = self.plate.center(x_gap,0).circle(radius)
                for i in range(self.y_holes + 1):
                    self.plate = self.plate.center(0,y_gap).circle(radius)
                for i in range(self.x_holes + 1):
                    self.plate = self.plate.center(-x_gap,0).circle(radius)
                for i in range(self.y_holes + 1):
                    self.plate = self.plate.center(0,-y_gap).circle(radius)
                self.plate = self.plate.center(-hole_distance, -hole_distance)
            else:
                log.error('Not adding holes. Why?!')
            self.plate = self.center(self.width/2 - self.kerf, self.height/2 - self.kerf) # move to center of the plate
        else:
            log.error('Unknown case type: %s', self.case_type)

        # Cut any specified holes
        if 'holes' in self.layers[layer]:
            self.cut_plate_holes(layer)

        # Cut any specified polygons
        if 'polygons' in self.layers[layer]:
            self.cut_plate_polygons(layer)

        # Draw the USB cutout
        if self.layers[layer].get('usb_cutout'):
            self.cut_usb_hole(layer)

        self.origin = (0,0)
        self.plate = self.plate.cutThruAll()
        return self.plate

    def layout_sandwich_holes(self):
        """Determine where screw holes should be placed.
        """
        log.debug("layout_sandwich_holes()")
        if self.layer_screw['count'] >= 4:
            holes = int(self.layer_screw['count'])
            if holes % 2 == 0 and holes >= 4: # holes needs to be even and the first 4 are put in the corners
                x = self.width + self.kerf*2   # x length to split
                y = self.height + self.kerf*2  # y length to split
                _x = 0                         # number of holes on each x side (not counting the corner holes)
                _y = 0                         # number of holes on each y side (not counting the corner holes)
                free = (holes-4)/2             # number of free holes to be placed on either x or y sides
                for f in range(free):          # loop through the available holes and place them
                    if x/(_x+1) == y/(_y+1):   # if equal, add the hole to the longer side
                        if x >= y:
                            _x += 1
                        else:
                            _y += 1
                    elif x/(_x+1) > y/(_y+1):
                        _x += 1
                    else:
                        _y += 1
                self.x_holes = _x
                self.y_holes = _y
            else:
                log.error('Invalid hole configuration! Need at least 4 holes and must be divisible by 2!')

    def cut_switch(self, switch_coord, key=None, layer='switch'):
        """Cut a switch opening

        switch_coord: Center of the switch

        key: A dictionary describing this key, if not provided a 1u key at 0,0 will be used.

        layer: The layer we're cutting
        """
        log.log(CUT_SWITCH, "cut_switch(switch_coord='%s', key='%s', layer='%s')", switch_coord, key, layer)
        if not key:
            key = {}

        width = key['w'] if 'w' in key else 1
        height = key['h'] if 'h' in key else 1
        switch_type = key['_t'] if '_t' in key else self.switch_type
        stab_type = key['_s'] if '_s' in key else self.stab_type
        kerf = key['_k']/2 if '_k' in key else self.kerf
        rotate_key = key['_r'] if '_r' in key else None
        rotate_stab = key['_rs'] if '_rs' in key else None
        center_offset = key['_co'] if '_co' in key else False

        # cut switch cutout
        rotate = None
        if 'h' in key and height > width:
            rotate = True
        points = []

        # Standard locations with no offset
        mx_height = 7 - kerf
        mx_width = 7 - kerf
        mx_wing_width = 7.8 - kerf
        alps_height = 6.4 - kerf
        alps_width = 7.8 - kerf
        wing_inside = 2.9 + kerf
        wing_outside = 6 - kerf
        mx_stab_inside_y = 4.75 - kerf
        mx_stab_inside_x = 8.575 + kerf
        stab_cherry_top_x = 5.5 - kerf
        # FIXME: Use more descriptive names here
        stab_4 = 10.3 + kerf
        stab_5 = 6.5 - kerf
        stab_6 = 13.6 - kerf
        mx_stab_outside_x = 15.225 - kerf
        stab_y_wire = 2.3 - kerf
        stab_bottom_y_wire = stab_y_wire - kerf
        stab_9 = 16.1 - kerf
        stab_cherry_wing_bottom_x = 0.5 - kerf
        stab_cherry_bottom_x = 6.75 - kerf
        stab_12 = 7.75 - kerf
        stab_13 = 6 - kerf
        stab_cherry_bottom_wing_bottom_y = 8 - kerf
        stab_cherry_half_width = 3.325 - kerf
        stab_cherry_bottom_wing_half_width = 1.65 - kerf
        stab_cherry_outside_x = 4.2 - kerf
        alps_stab_top_y = 4 + kerf
        alps_stab_bottom_y = 9 - kerf
        alps_stab_inside_x = (16.7 if width == 2.75 else 12.7) + kerf
        alps_stab_ouside_x = alps_stab_inside_x + 2.7 - kerf*2

        if layer == 'top':
            # Cut out openings the size of keycaps
            center_offset = False
            key_spacing = self.layers[layer].get('key_spacing', self.key_spacing)
            switch_type = 'mx'
            stab_type = 'cherry'
            if height > 1:
                mx_width = (((key_spacing/2) * height) + (height-0.5)) - kerf
            else:
                mx_width = (((key_spacing/2) * width) + (width-0.5)) - kerf
            mx_height = ((key_spacing/2) + 0.5) - kerf
        elif layer == 'reinforcing':
            offset = 1
            mx_height += offset
            mx_width += offset
            mx_wing_width = mx_width
            alps_height += offset
            alps_width += offset
            wing_inside += offset
            wing_outside += offset
            mx_stab_inside_x += offset
            stab_cherry_top_x += 2.5 if offset < 2.5 else offset
            stab_y_wire = mx_stab_inside_y = stab_cherry_top_x
            stab_4 += offset
            stab_5 += offset
            stab_6 += offset
            mx_stab_outside_x += offset
            stab_9 += offset
            stab_cherry_bottom_x += (4.3 - kerf) if offset < 4.3 else (offset - kerf)
            stab_cherry_wing_bottom_x = stab_bottom_y_wire = stab_cherry_bottom_wing_bottom_y = stab_13 = stab_12 = stab_cherry_bottom_x
            stab_cherry_half_width += offset
            stab_cherry_bottom_wing_half_width += offset
            stab_cherry_outside_x += offset
            alps_stab_top_y -= offset
            alps_stab_bottom_y += offset
            alps_stab_inside_x -= offset
            alps_stab_ouside_x += offset

        # Figure out our stabs now in case the switch itself is offset.
        length = width
        if rotate:
            length = height

        if length >= 2:
            x = STABILIZERS[length][0] if length in STABILIZERS else STABILIZERS[2][0]
            if not center_offset and layer != 'top':
                center_offset = STABILIZERS[length][1] if length in STABILIZERS else 0

        if center_offset > 0:
            # If the user has specified an offset stab (EG, 6U) we first move
            # to cut the offset switch hole, and later will move back to cut
            # the stabilizer.
            self.plate.center(center_offset, 0)

        if switch_type == 'mx':
            points = [
                (mx_width+self.grow_x,-mx_height-self.grow_y),
                (mx_width+self.grow_x,mx_height+self.grow_y),
                (-mx_width-self.grow_x,mx_height+self.grow_y),
                (-mx_width-self.grow_x,-mx_height-self.grow_y),
                (mx_width+self.grow_x,-mx_height-self.grow_y)
            ]
        elif switch_type == 'alpsmx':
            points = [
                (mx_width,-mx_height),
                (mx_width,-alps_height),
                (alps_width,-alps_height),
                (alps_width,alps_height),
                (mx_width,alps_height),
                (mx_width,mx_height),
                (-mx_width,mx_height),
                (-mx_width,alps_height),
                (-alps_width,alps_height),
                (-alps_width,-alps_height),
                (-mx_width,-alps_height),
                (-mx_width,-mx_height),
                (mx_width,-mx_height)
            ]
        elif switch_type == 'mx-open':
            points = [(mx_width,-mx_height)]
            if mx_width != mx_wing_width:
                points.extend([
                    (mx_width,-wing_outside),
                    (mx_wing_width,-wing_outside),
                    (mx_wing_width,-wing_inside),
                    (mx_width,-wing_inside),
                    (mx_width,wing_inside),
                    (mx_wing_width,wing_inside),
                    (mx_wing_width,wing_outside),
                    (mx_width,wing_outside)
                ])
            points.extend([
                (mx_width, mx_height),
                (-mx_width,mx_height)
            ])
            if mx_width != mx_wing_width:
                points.extend([
                    (-mx_width,wing_outside),
                    (-mx_wing_width,wing_outside),
                    (-mx_wing_width,wing_inside),
                    (-mx_width,wing_inside),
                    (-mx_width,-wing_inside),
                    (-mx_wing_width,-wing_inside),
                    (-mx_wing_width,-wing_outside),
                    (-mx_width,-wing_outside)
                ])
            points.extend([
                (-mx_width,-mx_height),
                (mx_width,-mx_height)
            ])
        elif switch_type == 'mx-open-rotatable':
            points = [
                (mx_width,-mx_height),
                (mx_width,-wing_outside),
                (alps_width,-wing_outside),
                (alps_width,-wing_inside),
                (mx_width,-wing_inside),
                (mx_width,wing_inside),
                (alps_width,wing_inside),
                (alps_width,wing_outside),
                (mx_width,wing_outside),
                (mx_width,mx_height),
                (wing_outside,mx_height),
                (wing_outside,alps_width),
                (wing_inside,alps_width),
                (wing_inside,mx_height),
                (-wing_inside,mx_height),
                (-wing_inside,alps_width),
                (-wing_outside,alps_width),
                (-wing_outside,mx_height),
                (-mx_width,mx_height),
                (-mx_width,wing_outside),
                (-alps_width,wing_outside),
                (-alps_width,wing_inside),
                (-mx_width,wing_inside),
                (-mx_width,-wing_inside),
                (-alps_width,-wing_inside),
                (-alps_width,-wing_outside),
                (-mx_width,-wing_outside),
                (-mx_width,-mx_height),
                (-wing_outside,-mx_height),
                (-wing_outside,-alps_width),
                (-wing_inside,-alps_width),
                (-wing_inside,-mx_height),
                (wing_inside,-mx_height),
                (wing_inside,-alps_width),
                (wing_outside,-alps_width),
                (wing_outside,-mx_height),
                (mx_width,-mx_height)
            ]
        elif switch_type == 'alps':
            points = [
                (alps_width,-alps_height),
                (alps_width,alps_height),
                (-alps_width,alps_height),
                (-alps_width,-alps_height),
                (alps_width,-alps_height),
            ]

        if rotate:
            points = rotate_points(points, 90, (0,0))
        if rotate_key:
            points = rotate_points(points, rotate_key, (0,0))

        self.plate = self.center(switch_coord[0], switch_coord[1]).polyline(points).cutThruAll()

        if center_offset > 0:
            # Move back to the center of the key/stabilizer
            self.plate.center(-center_offset, 0)

        # Cut stabilizers. We have different sections for 2U vs other sizes
        # because cherry 2U stabs are shaped differently from larger stabs.
        # This should be refactored for better readability.
        if stab_type not in ('cherry', 'cherry-costar', 'costar', 'matias', 'alps'):
            log.error('Unknown stab type %s! No stabilizer cut', stab_type)

        elif layer == 'top':
            # Don't cut stabs on top
            pass

        elif (width >= 2 and width < 3) or (rotate and height >= 2 and height < 3):
            # Cut 2 unit stabilizer cutout
            if stab_type in ('cherry', 'cherry-costar'):
                points = [
                    (mx_stab_inside_x,-mx_stab_inside_y),
                    (mx_stab_inside_x,-stab_cherry_top_x),
                    (mx_stab_outside_x,-stab_cherry_top_x),
                    (mx_stab_outside_x,-stab_y_wire),
                    (stab_9,-stab_y_wire),
                    (stab_9,stab_cherry_wing_bottom_x),
                    (mx_stab_outside_x,stab_cherry_wing_bottom_x),
                    (mx_stab_outside_x,stab_cherry_bottom_x),
                    (stab_6,stab_cherry_bottom_x),
                    (stab_6,stab_cherry_bottom_wing_bottom_y),
                    (stab_4,stab_cherry_bottom_wing_bottom_y),
                    (stab_4,stab_cherry_bottom_x),
                    (mx_stab_inside_x,stab_cherry_bottom_x),
                    (mx_stab_inside_x,stab_13),
                    (-mx_stab_inside_x,stab_13),
                    (-mx_stab_inside_x,stab_cherry_bottom_x),
                    (-stab_4,stab_cherry_bottom_x),
                    (-stab_4,stab_cherry_bottom_wing_bottom_y),
                    (-stab_6,stab_cherry_bottom_wing_bottom_y),
                    (-stab_6,stab_cherry_bottom_x),
                    (-mx_stab_outside_x,stab_cherry_bottom_x),
                    (-mx_stab_outside_x,stab_cherry_wing_bottom_x),
                    (-stab_9,stab_cherry_wing_bottom_x),
                    (-stab_9,-stab_y_wire),
                    (-mx_stab_outside_x,-stab_y_wire),
                    (-mx_stab_outside_x,-stab_cherry_top_x),
                    (-mx_stab_inside_x,-stab_cherry_top_x),
                    (-mx_stab_inside_x,-mx_stab_inside_y),
                    (mx_stab_inside_x,-mx_stab_inside_y),
                ]
                if rotate:
                    points = rotate_points(points, 90, (0,0))
                if rotate_stab:
                    points = rotate_points(points, rotate_stab, (0,0))
                self.plate = self.plate.polyline(points).cutThruAll()

            if stab_type in ('costar', 'cherry-costar'):
                points_l = [
                    (-stab_4,-stab_5),
                    (-stab_6,-stab_5),
                    (-stab_6,stab_12),
                    (-stab_4,stab_12),
                    (-stab_4,-stab_5)
                ]
                points_r = [
                    (stab_4,-stab_5),
                    (stab_6,-stab_5),
                    (stab_6,stab_12),
                    (stab_4,stab_12),
                    (stab_4,-stab_5)
                ]
                if rotate:
                    points_l = rotate_points(points_l, 90, (0,0))
                    points_r = rotate_points(points_r, 90, (0,0))
                if rotate_stab:
                    points_l = rotate_points(points_l, rotate_stab, (0,0))
                    points_r = rotate_points(points_r, rotate_stab, (0,0))
                self.plate = self.plate.polyline(points_l)
                self.plate = self.plate.polyline(points_r).cutThruAll()

            if stab_type in ('alps', 'matias'):
                points_r = [
                    (alps_stab_inside_x, alps_stab_top_y),
                    (alps_stab_ouside_x, alps_stab_top_y),
                    (alps_stab_ouside_x, alps_stab_bottom_y),
                    (alps_stab_inside_x, alps_stab_bottom_y),
                    (alps_stab_inside_x, alps_stab_top_y)
                ]
                points_l = [
                    (-alps_stab_inside_x, alps_stab_top_y),
                    (-alps_stab_ouside_x, alps_stab_top_y),
                    (-alps_stab_ouside_x, alps_stab_bottom_y),
                    (-alps_stab_inside_x, alps_stab_bottom_y),
                    (-alps_stab_inside_x, alps_stab_top_y)
                ]

                if rotate:
                    points_l = rotate_points(points_l, 270, (0,0))
                    points_r = rotate_points(points_r, 270, (0,0))
                if rotate_stab:
                    points_l = rotate_points(points_l, rotate_stab, (0,0))
                    points_r = rotate_points(points_r, rotate_stab, (0,0))
                self.plate = self.plate.polyline(points_l)
                self.plate = self.plate.polyline(points_r).cutThruAll()

        # Cut larger stabilizer cutouts
        elif (width >= 3) or (rotate and height >= 3):
            if stab_type == 'cherry-costar':
                points = [
                    (x-stab_cherry_half_width,-stab_y_wire),
                    (x-stab_cherry_half_width,-stab_cherry_top_x),
                    (x-stab_cherry_bottom_wing_half_width,-stab_cherry_top_x),
                    (x-stab_cherry_bottom_wing_half_width,-stab_5),
                    (x+stab_cherry_bottom_wing_half_width,-stab_5),
                    (x+stab_cherry_bottom_wing_half_width,-stab_cherry_top_x),
                    (x+stab_cherry_half_width,-stab_cherry_top_x),
                    (x+stab_cherry_half_width,-stab_y_wire),
                    (x+stab_cherry_outside_x,-stab_y_wire),
                    (x+stab_cherry_outside_x,stab_cherry_wing_bottom_x),
                    (x+stab_cherry_half_width,stab_cherry_wing_bottom_x),
                    (x+stab_cherry_half_width,stab_cherry_bottom_x),
                    (x+stab_cherry_bottom_wing_half_width,stab_cherry_bottom_x),
                    (x+stab_cherry_bottom_wing_half_width,stab_12),
                    (x-stab_cherry_bottom_wing_half_width,stab_12),
                    (x-stab_cherry_bottom_wing_half_width,stab_cherry_bottom_x),
                    (x-stab_cherry_half_width,stab_cherry_bottom_x),
                    (x-stab_cherry_half_width,stab_y_wire),
                    (-x+stab_cherry_half_width,stab_y_wire),
                    (-x+stab_cherry_half_width,stab_cherry_bottom_x),
                    (-x+stab_cherry_bottom_wing_half_width,stab_cherry_bottom_x),
                    (-x+stab_cherry_bottom_wing_half_width,stab_12),
                    (-x-stab_cherry_bottom_wing_half_width,stab_12),
                    (-x-stab_cherry_bottom_wing_half_width,stab_cherry_bottom_x),
                    (-x-stab_cherry_half_width,stab_cherry_bottom_x),
                    (-x-stab_cherry_half_width,stab_cherry_wing_bottom_x),
                    (-x-stab_cherry_outside_x,stab_cherry_wing_bottom_x),
                    (-x-stab_cherry_outside_x,-stab_y_wire),
                    (-x-stab_cherry_half_width,-stab_y_wire),
                    (-x-stab_cherry_half_width,-stab_cherry_top_x),
                    (-x-stab_cherry_bottom_wing_half_width,-stab_cherry_top_x),
                    (-x-stab_cherry_bottom_wing_half_width,-stab_5),
                    (-x+stab_cherry_bottom_wing_half_width,-stab_5),
                    (-x+stab_cherry_bottom_wing_half_width,-stab_cherry_top_x),
                    (-x+stab_cherry_half_width,-stab_cherry_top_x),
                    (-x+stab_cherry_half_width,-stab_y_wire),
                    (x-stab_cherry_half_width,-stab_y_wire)
                ]
                if rotate:
                    points = rotate_points(points, 90, (0,0))
                if rotate_stab:
                    points = rotate_points(points, rotate_stab, (0,0))
                self.plate = self.plate.polyline(points).cutThruAll()
            elif stab_type == 'cherry':
                points = [
                    (x - stab_cherry_half_width, -stab_y_wire),#1
                    (x - stab_cherry_half_width, -stab_cherry_top_x),#2
                    (x + stab_cherry_half_width, -stab_cherry_top_x),#3
                    (x + stab_cherry_half_width, -stab_y_wire),#4
                    (x + stab_cherry_outside_x, -stab_y_wire),#5
                    (x + stab_cherry_outside_x, stab_cherry_wing_bottom_x),#6
                    (x + stab_cherry_half_width, stab_cherry_wing_bottom_x),#7
                    (x + stab_cherry_half_width, stab_cherry_bottom_x),#8
                    (x + stab_cherry_bottom_wing_half_width, stab_cherry_bottom_x),#9
                    (x + stab_cherry_bottom_wing_half_width, stab_cherry_bottom_wing_bottom_y),#10
                    (x - stab_cherry_bottom_wing_half_width, stab_cherry_bottom_wing_bottom_y),#11
                    (x - stab_cherry_bottom_wing_half_width, stab_cherry_bottom_x),#12
                    (x - stab_cherry_half_width, stab_cherry_bottom_x),#13
                    (x - stab_cherry_half_width, stab_bottom_y_wire),#14
                    (-x + stab_cherry_half_width, stab_bottom_y_wire),#15
                    (-x + stab_cherry_half_width, stab_cherry_bottom_x),#16
                    (-x + stab_cherry_bottom_wing_half_width, stab_cherry_bottom_x),#17
                    (-x + stab_cherry_bottom_wing_half_width, stab_cherry_bottom_wing_bottom_y),#18
                    (-x - stab_cherry_bottom_wing_half_width, stab_cherry_bottom_wing_bottom_y),#19
                    (-x - stab_cherry_bottom_wing_half_width, stab_cherry_bottom_x),#20
                    (-x - stab_cherry_half_width, stab_cherry_bottom_x),#21
                    (-x - stab_cherry_half_width, stab_cherry_wing_bottom_x),#22
                    (-x - stab_cherry_outside_x, stab_cherry_wing_bottom_x),#23
                    (-x - stab_cherry_outside_x, -stab_y_wire),#24
                    (-x - stab_cherry_half_width, -stab_y_wire),#25
                    (-x - stab_cherry_half_width, -stab_cherry_top_x),#26
                    (-x + stab_cherry_half_width, -stab_cherry_top_x),#27
                    (-x + stab_cherry_half_width, -stab_y_wire),#28
                    (x - stab_cherry_half_width, -stab_y_wire),#1
                ]
                if rotate:
                    points = rotate_points(points, 90, (0,0))
                if rotate_stab:
                    points = rotate_points(points, rotate_stab, (0,0))
                self.plate = self.plate.polyline(points).cutThruAll()
            elif stab_type in ('costar', 'matias'):
                points_l = [
                    (-x+stab_cherry_bottom_wing_half_width,-stab_5),
                    (-x-stab_cherry_bottom_wing_half_width,-stab_5),
                    (-x-stab_cherry_bottom_wing_half_width,stab_12),
                    (-x+stab_cherry_bottom_wing_half_width,stab_12),
                    (-x+stab_cherry_bottom_wing_half_width,-stab_5)
                ]
                points_r = [
                    (x-stab_cherry_bottom_wing_half_width,-stab_5),
                    (x+stab_cherry_bottom_wing_half_width,-stab_5),
                    (x+stab_cherry_bottom_wing_half_width,stab_12),
                    (x-stab_cherry_bottom_wing_half_width,stab_12),
                    (x-stab_cherry_bottom_wing_half_width,-stab_5)
                ]
                if rotate:
                    points_l = rotate_points(points_l, 90, (0,0))
                    points_r = rotate_points(points_r, 90, (0,0))
                if rotate_stab:
                    points_l = rotate_points(points_l, rotate_stab, (0,0))
                    points_r = rotate_points(points_r, rotate_stab, (0,0))
                self.plate = self.plate.polyline(points_l)
                self.plate = self.plate.polyline(points_r).cutThruAll()
            elif stab_type == 'alps':
                # Alps stabilizers
                if width == 6.5:
                    inside_x = alps_stab_inside_x + 31.3
                else:
                    log.error("We don't know how far apart stabs are for alps of %s width!" % width)
                    inside_x = alps_stab_inside_x + 30

                outside_x = inside_x + 2.7 - self.kerf*2
                points_r = [
                    (inside_x, alps_stab_top_y),
                    (outside_x, alps_stab_top_y),
                    (outside_x, alps_stab_bottom_y),
                    (inside_x, alps_stab_bottom_y),
                    (inside_x, alps_stab_top_y)
                ]
                points_l = [
                    (-inside_x, alps_stab_top_y),
                    (-outside_x, alps_stab_top_y),
                    (-outside_x, alps_stab_bottom_y),
                    (-inside_x, alps_stab_bottom_y),
                    (-inside_x, alps_stab_top_y)
                ]

                if rotate:
                    points_l = rotate_points(points_l, 90, (0, 0))
                    points_r = rotate_points(points_r, 90, (0, 0))
                if rotate_stab:
                    points_l = rotate_points(points_l, rotate_stab, (0, 0))
                    points_r = rotate_points(points_r, rotate_stab, (0, 0))
                self.plate = self.plate.polyline(points_l)
                self.plate = self.plate.polyline(points_r).cutThruAll()
            else:
                log.error('Unknown stab type %s! No stabilizer cut', stab_type)

        self.x_off += switch_coord[0]
        return self.plate

    def recenter(self):
        """Move back to the centerpoint of the plate
        """
        log.log(CENTER_MOVE, "recenter()")
        self.plate.center(-self.origin[0], -self.origin[1])
        self.origin = (0,0)

        return self.plate

    def center(self, x, y):
        """Move the center point and record how far we have moved relative to the center of the plate.
        """
        log.log(CENTER_MOVE, "center(plate='%s', x='%s', y='%s')", self.plate, x, y)
        self.origin = (self.origin[0]+x, self.origin[1]+y)

        return self.plate.center(x, y)

    def __repr__(self):
        """Print out all KeyboardCase object configuration settings.
        """
        log.debug('__repr__()')
        return {
            'plate_layout': self.layout,
            'switch_type': self.switch_type,
            'stabilizer_type': self.stab_type,
            'case_type_and_holes': self.case,
            'width_padding': self.x_pad,
            'height_padding': self.y_pad,
            'pcb_width_padding': self.x_pcb_pad,
            'pcb_height_padding': self.y_pcb_pad,
            'plate_corners': self.corners,
            'kerf': self.kerf
        }

    def export(self, layer, directory='static/exports'):
        """Export the specified layer to the formats specified in self.formats.
        """
        log.debug("export(layer='%s', directory='%s')", layer, directory)
        log.info("Exporting %s layer for %s", layer, self.name)
        self.exports[layer] = []
        dirname = '%s/%s' % (directory, self.name)
        basename = '%s/%s_layer' % (dirname, layer)

        if not exists(dirname):
            makedirs(dirname)

        # Cut anything drawn on the plate
        self.plate = self.plate.cutThruAll()

        # draw the part so we can export it
        Part.show(self.plate.val().wrapped)
        doc = FreeCAD.ActiveDocument

        # export the drawing into different formats
        if 'js' in self.formats:
            with open(basename+".js", "w") as f:
                cadquery.exporters.exportShape(self.plate, 'TJS', f)
                self.exports[layer].append({'name': 'js', 'url': '/'+basename+'.js'})
                log.info("Exported 'JS' to %s.js", basename)

        if 'brp' in self.formats:
            Part.export(doc.Objects, basename+".brp")
            self.exports[layer].append({'name': 'brp', 'url': '/'+basename+'.brp'})
            log.info("Exported 'BRP' to %s.brp", basename)

        if 'stp' in self.formats:
            Part.export(doc.Objects, basename+".stp")
            self.exports[layer].append({'name': 'stp', 'url': '/'+basename+'.stp'})
            log.info("Exported 'STP' to %s.stp", basename)

        if 'stl' in self.formats:
            Mesh.export(doc.Objects, basename+".stl")
            self.exports[layer].append({'name': 'stl', 'url': '/'+basename+'.stl'})
            log.info("Exported 'STL' to %s.stl", basename)

        if 'dxf' in self.formats:
            importDXF.export(doc.Objects, basename+".dxf")
            self.exports[layer].append({'name': 'dxf', 'url': '/'+basename+'.dxf'})
            log.info("Exported 'DXF' to %s.dxf", basename)

        if 'svg' in self.formats:
            importSVG.export(doc.Objects, basename+".svg")
            self.exports[layer].append({'name': 'svg', 'url': '/'+basename+'.svg'})
            log.info("Exported 'SVG' to %s.svg", basename)

        if 'json' in self.formats and layer == 'switch':
            with open(basename+".json", 'w') as json_file:
                json_file.write(repr(self))
            self.exports[layer].append({'name': 'json', 'url': '/'+basename+'.json'})
            log.info("Exported 'JSON' to %s.json", basename)

        # remove all the documents from the view before we move on
        for o in doc.Objects:
            doc.removeObject(o.Label)
