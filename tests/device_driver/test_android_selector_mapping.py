from verdict.core.models import Selector
from verdict.device_driver.android import _to_u2_kwargs


def test_maps_all_selector_fields_to_uiautomator2_kwargs():
    selector = Selector(resource_id="rid", text="hi", description="desc", class_name="cls")
    assert _to_u2_kwargs(selector) == {
        "resourceId": "rid",
        "text": "hi",
        "description": "desc",
        "className": "cls",
    }


def test_omits_unset_fields():
    selector = Selector(resource_id="rid")
    assert _to_u2_kwargs(selector) == {"resourceId": "rid"}
