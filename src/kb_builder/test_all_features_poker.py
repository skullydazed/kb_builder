"""Test the basic functionality with a simple plate including every switch type.
"""
import filecmp
from builder import KeyboardCase
from functions import load_layout_file


def test_all_features_poker():
    layout = load_layout_file('test_all_features_poker.kle')
    case = KeyboardCase(layout, ['dxf'])

    case.create_switch_layer('reinforcing')
    case.export('reinforcing', 'test_exports')

    case.create_switch_layer('switch')
    case.export('switch', 'test_exports')

    assert case.name == 'test_all_features_poker'
    assert case.formats == ['dxf']
    assert case.kerf == 0.1
    assert case.width == 247.65
    assert case.height == 95.25
    #assert case.inside_width == 247.45 # FIXME: Why doesn't this work?
    assert case.inside_height == 95.05

    for layer in ('reinforcing', 'switch'):
        assert layer in case.layers
        assert filecmp.cmp('test_exports/%s/switch_layer.dxf' % case.name, 'test_exports/%s.knowngood/switch_layer.dxf' % case.name) == True

    return True
