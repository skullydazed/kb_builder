"""Test the basic functionality with a simple plate including every switch type.
"""
import filecmp
from builder import KeyboardCase
from functions import load_layout_file


def test_all_features_sandwich():
    layout = load_layout_file('test_all_features_sandwich.kle')
    case = KeyboardCase(layout, ['dxf'])

    case.create_bottom_layer('bottom')
    case.export('bottom', 'test_exports')

    case.create_middle_layer('closed')
    case.export('closed', 'test_exports')

    case.create_middle_layer('open')
    case.export('open', 'test_exports')

    case.create_switch_layer('reinforcing')
    case.export('reinforcing', 'test_exports')

    case.create_switch_layer('switch')
    case.export('switch', 'test_exports')

    case.create_switch_layer('top')
    case.export('top', 'test_exports')

    assert case.name == 'test_all_features_sandwich'
    assert case.formats == ['dxf']
    assert case.kerf == 0.1
    assert case.width == 259.65
    assert case.height == 107.25
    assert case.inside_width == 251.45
    assert case.inside_height == 99.05

    for layer in ('bottom', 'closed', 'open', 'reinforcing', 'switch', 'top'):
        assert layer in case.layers
        assert filecmp.cmp('test_exports/switch_%s.dxf' % case.name, 'test_exports/switch_%s.dxf.knowngood' % case.name) == True

    return True
