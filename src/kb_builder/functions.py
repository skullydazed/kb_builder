"""Helpful functions.
"""
import logging
import math

log = logging.getLogger()

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
