"""Test the basic functionality with a simple plate including every switch type.
"""
import filecmp
from builder import KeyboardCase
from functions import load_layout_file


def test_all_shapes():
    layout = load_layout_file('test_all_shapes.kle')
    case = KeyboardCase(layout, ['dxf'])
    case.create_switch_layer('switch')
    case.export('switch', 'test_exports')

    # Basic checks
    assert case.name == '4ac3f3a2dc4d5b2225bf03f0f83f047960846a30'
    assert case.formats == ['dxf']
    assert case.kerf == 0
    assert case.layers == {'switch': {}}
    assert case.width == 247.65
    assert case.height == 95.25
    assert case.inside_width == 247.65
    assert case.inside_height == 95.25

    # Make sure the DXF matches the reference DXF
    assert filecmp.cmp('test_exports/switch_%s.dxf' % case.name, 'test_exports/switch_%s.dxf.knowngood' % case.name) == True

    return True
