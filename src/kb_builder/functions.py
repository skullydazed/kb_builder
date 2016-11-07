"""Helpful functions.
"""
import hjson
import logging
import math


log = logging.getLogger()


def load_layout(layout_text):
    """Loads a KLE layout file and returns a list of rows.
    """
    log.debug('load_layout(%s)', layout_text)
    layout = []
    keyboard_properties = {}

    # Wrap in a dictionary so HJSON will accept keyboard-layout-editor raw data
    for row in hjson.loads('{"layout": [' + layout_text + ']}')['layout']:
        if isinstance(row, dict):
            keyboard_properties.update(row)
        else:
            layout.append(row)

    layout.insert(0, keyboard_properties)

    return layout


def load_layout_file(file):
    """Loads a KLE layout file and returns a list of rows.
    """
    log.debug('load_layout_file(%s)', file)
    return load_layout(open(file).read())


def rotate_points(points, radians, rotate_point):
    """Rotate a sequence of points.

    points: the points to rotate

    radians: the number of degrees to rotate

    rotate_point: the coordinate to rotate around
    """
    log.debug("rotate_points(points='%s', radians='%s', rotate_point='%s')", points, radians, rotate_point)

    def calculate_point(point):
        log.debug("calculate_point(point='%s')", point)
        return (
            math.cos(math.radians(radians)) * (point[0]-rotate_point[0]) - math.sin(math.radians(radians)) * (point[1]-rotate_point[1]) + rotate_point[0],
            math.sin(math.radians(radians)) * (point[0]-rotate_point[0]) + math.cos(math.radians(radians)) * (point[1]-rotate_point[1]) + rotate_point[1]
        )

    return map(calculate_point, points)
