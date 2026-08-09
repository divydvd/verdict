from verdict.device_driver.android_hierarchy import parse_hierarchy_xml

SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" content-desc=""
        bounds="[0,0][1080,2280]">
    <node index="0" text="" resource-id="com.example:id/text_field" class="android.widget.EditText"
          content-desc="" bounds="[40,100][1040,200]" />
    <node index="1" text="" resource-id="" class="android.widget.ImageView"
          content-desc="ai_suggestion_chip" bounds="[40,300][400,360]" />
  </node>
</hierarchy>
"""


def test_parse_hierarchy_xml_builds_tree():
    root = parse_hierarchy_xml(SAMPLE_XML)

    assert root is not None
    assert root.class_name == "android.widget.FrameLayout"
    assert root.bounds == (0, 0, 1080, 2280)
    assert len(root.children) == 2
    assert root.children[0].resource_id == "com.example:id/text_field"
    assert root.children[1].content_desc == "ai_suggestion_chip"
    assert root.children[1].bounds == (40, 300, 400, 360)


def test_parse_hierarchy_xml_blank_attrs_become_none():
    root = parse_hierarchy_xml(SAMPLE_XML)
    assert root is not None
    assert root.text is None
    assert root.resource_id is None


def test_parse_hierarchy_xml_empty_hierarchy_returns_none():
    root = parse_hierarchy_xml("<hierarchy rotation='0'></hierarchy>")
    assert root is None
