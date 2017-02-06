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
    assert case.name == '50660d1f6922253e5e1dccdedb2b4e4812c1fdc4'
    assert case.formats == ['dxf']
    assert case.kerf == 0
    assert case.layers == {'switch': {}}
    assert case.width == 247.65
    assert case.height == 95.25
    assert case.inside_width == 247.65
    assert case.inside_height == 95.25

    # Make sure the DXF matches the reference DXF
    assert filecmp.cmp('test_exports/%s/switch_layer.dxf' % case.name, 'test_exports/%s.knowngood/switch_layer.dxf' % case.name) == True

    return True
