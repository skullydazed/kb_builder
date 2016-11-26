"""Test the basic functionality with a simple plate including every switch type.
"""
import filecmp
from builder import KeyboardCase
from functions import load_layout_file


def test_numpad():
    layout = load_layout_file('test_numpad.kle')
    layout[0]['name'] = 'test_numpad'
    case = KeyboardCase(layout, ['dxf'])
    case.create_switch_layer('switch')
    case.export('switch', 'test_exports')

    # Basic checks
    assert case.name == 'test_numpad'
    assert case.formats == ['dxf']
    assert case.kerf == 0
    assert case.layers == {'switch': {}}
    assert case.width == 76.2
    assert case.height == 95.25
    assert case.inside_width == 76.2
    assert case.inside_height == 95.25

    # Make sure the DXF matches the reference DXF
    assert filecmp.cmp('test_exports/switch_%s.dxf' % case.name, 'test_exports/switch_%s.dxf.knowngood' % case.name) == True

    return True
