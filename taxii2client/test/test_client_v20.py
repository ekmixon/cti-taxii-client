import datetime
import json

import pytest
import requests
import responses
import six

from taxii2client import (
    DEFAULT_USER_AGENT, MEDIA_TYPE_STIX_V20, MEDIA_TYPE_TAXII_V20
)
from taxii2client.common import (
    TokenAuth, _filter_kwargs_to_query_params, _HTTPConnection, _TAXIIEndpoint
)
from taxii2client.exceptions import (
    AccessError, InvalidArgumentsError, InvalidJSONError,
    TAXIIServiceException, ValidationError
)
from taxii2client.v20 import ApiRoot, Collection, Server, Status, as_pages

TAXII_SERVER = "example.com"
DISCOVERY_URL = f"https://{TAXII_SERVER}/taxii/"
API_ROOT_URL = f"https://{TAXII_SERVER}/api1/"
COLLECTIONS_URL = f"{API_ROOT_URL}collections/"
COLLECTION_URL = f"{COLLECTIONS_URL}91a7b528-80eb-42ed-a74d-c6fbd5a26116/"
OBJECTS_URL = f"{COLLECTION_URL}objects/"
GET_OBJECTS_URL = OBJECTS_URL
ADD_OBJECTS_URL = OBJECTS_URL
WRITABLE_COLLECTION_URL = (
    f"{COLLECTIONS_URL}e278b87e-0f9b-4c63-a34c-c8f0b3e91acb/"
)

ADD_WRITABLE_OBJECTS_URL = f"{WRITABLE_COLLECTION_URL}objects/"
GET_OBJECT_URL = (
    f"{OBJECTS_URL}indicator--252c7c11-daf2-42bd-843b-be65edca9f61/"
)

MANIFEST_URL = f"{COLLECTION_URL}manifest/"
STATUS_ID = "2d086da7-4bdc-4f91-900e-d77486753710"
STATUS_URL = f"{API_ROOT_URL}status/{STATUS_ID}/"

# These responses are provided as examples in the TAXII 2.0 specification.
DISCOVERY_RESPONSE = """{
  "title": "Some TAXII Server",
  "description": "This TAXII Server contains a listing of...",
  "contact": "string containing contact information",
  "default": "https://example.com/api2/",
  "api_roots": [
    "https://example.com/api1/",
    "https://example.com/api2/",
    "https://example.net/trustgroup1/"
  ]
}"""
API_ROOT_RESPONSE = """{
  "title": "Malware Research Group",
  "description": "A trust group setup for malware researchers",
  "versions": ["taxii-2.0"],
  "max_content_length": 9765625
}"""
COLLECTIONS_RESPONSE = """{
  "collections": [
    {
      "id": "91a7b528-80eb-42ed-a74d-c6fbd5a26116",
      "title": "High Value Indicator Collection",
      "description": "This data collection is for collecting high value IOCs",
      "can_read": true,
      "can_write": false,
      "media_types": [
        "application/vnd.oasis.stix+json; version=2.0"
      ]
    },
    {
      "id": "52892447-4d7e-4f70-b94d-d7f22742ff63",
      "title": "Indicators from the past 24-hours",
      "description": "This data collection is for collecting current IOCs",
      "can_read": true,
      "can_write": false,
      "media_types": [
        "application/vnd.oasis.stix+json; version=2.0"
      ]
    }
  ]
}"""
COLLECTION_RESPONSE = """{
  "id": "91a7b528-80eb-42ed-a74d-c6fbd5a26116",
  "title": "High Value Indicator Collection",
  "description": "This data collection is for collecting high value IOCs",
  "can_read": true,
  "can_write": false,
  "media_types": [
    "application/vnd.oasis.stix+json; version=2.0"
  ]
}"""

# This collection is not in the spec.
WRITABLE_COLLECTION = """{
  "id": "e278b87e-0f9b-4c63-a34c-c8f0b3e91acb",
  "title": "Writable Collection",
  "description": "This collection is a dropbox for submitting indicators",
  "can_read": false,
  "can_write": true,
  "media_types": [
    "application/vnd.oasis.stix+json; version=2.0"
  ]
}"""


STIX_OBJECT = """
{
  "type": "indicator",
  "id": "indicator--252c7c11-daf2-42bd-843b-be65edca9f61",
  "created": "2016-04-06T20:03:48.000Z",
  "modified": "2016-04-06T20:03:48.000Z",
  "pattern": "[ file:hashes.MD5 = 'd41d8cd98f00b204e9800998ecf8427e' ]",
  "valid_from": "2016-01-01T00:00:00Z"
}
"""


# This bundle is used as the response to get_objects(), and also the bundle
# POST'ed with add_objects().
STIX_BUNDLE = f"""{{
  "type": "bundle",
  "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
  "spec_version": "2.0",
  "objects": [
    {STIX_OBJECT}
  ]
}}"""
GET_OBJECTS_RESPONSE = STIX_BUNDLE
# get_object() still returns a bundle. In this case, the bundle has only one
# object (the correct one.)
GET_OBJECT_RESPONSE = GET_OBJECTS_RESPONSE

# This is the expected response when calling ADD_OBJECTS with the STIX_BUNDLE
# above. There is only one object, and it was added successfully. This response
# is not in the spec.
ADD_OBJECTS_RESPONSE = """{
  "id": "350dae03-d2d8-4bd3-bc1d-8160589693e3",
  "status": "complete",
  "request_timestamp": "2016-11-02T12:34:34.12345Z",
  "total_count": 1,
  "success_count": 1,
  "successes": [
    "indicator--252c7c11-daf2-42bd-843b-be65edca9f61"
  ],
  "failure_count": 0,
  "pending_count": 0
}"""

# This is the response in Section 5.4 of the spec. It implies a larger
# bundle than what is provided in the example.
ADD_OBJECTS_RESPONSE_FROM_SPEC = """{
  "id": "2d086da7-4bdc-4f91-900e-d77486753710",
  "status": "pending",
  "request_timestamp": "2016-11-02T12:34:34.12345Z",
  "total_count": 4,
  "success_count": 1,
  "successes": [
    "indicator--c410e480-e42b-47d1-9476-85307c12bcbf"
  ],
  "failure_count": 0,
  "pending_count": 3
}"""


GET_MANIFEST_RESPONSE = """{
  "objects": [
    {
      "id": "indicator--29aba82c-5393-42a8-9edb-6a2cb1df070b",
      "date_added": "2016-11-01T03:04:05Z",
      "versions": ["2016-11-03T12:30:59.000Z","2016-12-03T12:30:59.000Z"],
      "media_types": ["application/vnd.oasis.stix+json; version=2.0"]
    },
    {
      "id": "indicator--ef0b28e1-308c-4a30-8770-9b4851b260a5",
      "date_added": "2016-11-01T10:29:05Z",
      "versions": ["2016-11-03T12:30:59.000Z"],
      "media_types": ["application/vnd.oasis.stix+json; version=2.0"]
    }
  ]
}"""

STATUS_RESPONSE = """{
  "id": "2d086da7-4bdc-4f91-900e-d77486753710",
  "status": "pending",
  "request_timestamp": "2016-11-02T12:34:34.12345Z",
  "total_count": 4,
  "success_count": 1,
  "successes": [
    "indicator--c410e480-e42b-47d1-9476-85307c12bcbf"
  ],
  "failure_count": 1,
  "failures": [
    {
      "id": "malware--664fa29d-bf65-4f28-a667-bdb76f29ec98",
      "message": "Unable to process object"
    }
  ],
  "pending_count": 2,
  "pendings": [
    "indicator--252c7c11-daf2-42bd-843b-be65edca9f61",
    "relationship--045585ad-a22f-4333-af33-bfd503a683b5"
  ]
}"""

BAD_DISCOVERY_RESPONSE = """{"title":"""

ERROR_MESSAGE = """{
  "title": "Error condition XYZ",
  "description": "This error is caused when the application tries to access data...",
  "error_id": "1234",
  "error_code": "581234",
  "http_status": "%s",
  "external_details": "http://example.com/ticketnumber1/errorid-1234",
  "details": {
    "somekey1": "somevalue",
    "somekey2": "some other value"
  }
}"""


@pytest.fixture
def status_dict():
    return {
        "id": "2d086da7-4bdc-4f91-900e-d77486753710",
        "status": "pending",
        "request_timestamp": "2016-11-02T12:34:34.12345Z",
        "total_count": 4,
        "success_count": 1,
        "successes": [
            "indicator--c410e480-e42b-47d1-9476-85307c12bcbf"
        ],
        "failure_count": 1,
        "failures": [
            {
              "id": "malware--664fa29d-bf65-4f28-a667-bdb76f29ec98",
              "message": "Unable to process object"
            }
        ],
        "pending_count": 2,
        "pendings": [
            "indicator--252c7c11-daf2-42bd-843b-be65edca9f61",
            "relationship--045585ad-a22f-4333-af33-bfd503a683b5"
        ]
    }


@pytest.fixture
def collection_dict():
    return {
        "id": "e278b87e-0f9b-4c63-a34c-c8f0b3e91acb",
        "title": "Writable Collection",
        "description": "This collection is a dropbox for submitting indicators",
        "can_read": False,
        "can_write": True,
        "media_types": [
            "application/vnd.oasis.stix+json; version=2.0"
        ]
    }


@pytest.fixture
def server():
    """Default server object for example.com"""
    return Server(DISCOVERY_URL, user="foo", password="bar")


@pytest.fixture
def api_root():
    """Default API Root object"""
    return ApiRoot(API_ROOT_URL)


@pytest.fixture
def collection():
    """Default Collection object"""
    # The collection response is needed to get information about the collection
    set_collection_response()
    return Collection(COLLECTION_URL)


@pytest.fixture
def writable_collection():
    """Collection with 'can_write' set to 'true'."""
    set_collection_response(WRITABLE_COLLECTION_URL, WRITABLE_COLLECTION)
    return Collection(WRITABLE_COLLECTION_URL)


@pytest.fixture
def bad_writable_collection():
    """Collection with 'can_write=true', but the COLLECTION_URL is different
    from the one in the response"""
    set_collection_response(response=WRITABLE_COLLECTION)
    return Collection(COLLECTION_URL)


def set_api_root_response(response):
    responses.add(responses.GET, API_ROOT_URL, body=response,
                  status=200, content_type=MEDIA_TYPE_TAXII_V20)


def set_discovery_response(response):
    responses.add(responses.GET, DISCOVERY_URL, body=response, status=200,
                  content_type=MEDIA_TYPE_TAXII_V20)


def set_collections_response():
    responses.add(responses.GET, COLLECTIONS_URL, COLLECTIONS_RESPONSE,
                  status=200, content_type=MEDIA_TYPE_TAXII_V20)


def set_collection_response(url=COLLECTION_URL, response=COLLECTION_RESPONSE):
    responses.add(responses.GET, url, response, status=200,
                  content_type=MEDIA_TYPE_TAXII_V20)


def set_status_response():
    responses.add(responses.GET, STATUS_URL, STATUS_RESPONSE,
                  status=200, content_type=MEDIA_TYPE_TAXII_V20)


@responses.activate
def test_server_discovery(server):
    set_discovery_response(DISCOVERY_RESPONSE)

    assert server._loaded is False
    assert server.title == "Some TAXII Server"
    assert server._loaded is True
    assert server.description == "This TAXII Server contains a listing of..."
    assert server.contact == "string containing contact information"
    assert len(server.api_roots) == 3
    assert server.default is not None

    assert server.api_roots[1] == server.default

    api_root = server.api_roots[0]
    assert api_root.url == API_ROOT_URL
    assert api_root._loaded_information is False
    assert api_root._loaded_collections is False

    discovery_dict = json.loads(DISCOVERY_RESPONSE)
    assert server._raw == discovery_dict


@responses.activate
def test_bad_json_response(server):
    set_discovery_response(BAD_DISCOVERY_RESPONSE)

    with pytest.raises(InvalidJSONError):
        # Just do something to trigger a request
        server.title


@responses.activate
def test_minimal_discovery_response(server):
    # `title` is the only required field on a Discovery Response
    set_discovery_response('{"title": "Some TAXII Server"}')

    assert server.title == "Some TAXII Server"
    assert server.description is None
    assert server.contact is None
    assert server.api_roots == []
    assert server.default is None


@responses.activate
def test_discovery_with_no_default(server):
    response = """{
      "title": "Some TAXII Server",
      "description": "This TAXII Server contains a listing of...",
      "contact": "string containing contact information",
      "api_roots": [
        "https://example.com/api1/",
        "https://example.com/api2/",
        "https://example.net/trustgroup1/"
      ]
    }"""
    set_discovery_response(response)

    assert len(server.api_roots) == 3
    assert server.default is None


@responses.activate
def test_discovery_with_no_title(server):
    response = """{
      "description": "This TAXII Server contains a listing of...",
      "contact": "string containing contact information",
      "api_roots": [
        "https://example.com/api1/",
        "https://example.com/api2/",
        "https://example.net/trustgroup1/"
      ]
    }"""
    set_discovery_response(response)
    with pytest.raises(ValidationError) as excinfo:
        server.refresh()

    assert "No 'title' in Server Discovery for request 'https://example.com/taxii/'" == str(excinfo.value)


@responses.activate
def test_api_root_no_title(api_root):
    set_api_root_response("""{
      "description": "A trust group setup for malware researchers",
      "versions": ["taxii-2.0"],
      "max_content_length": 9765625
    }""")
    with pytest.raises(ValidationError) as excinfo:
        assert api_root._loaded_information is False
        api_root.refresh_information()

    assert "No 'title' in API Root for request 'https://example.com/api1/'" == str(excinfo.value)


@responses.activate
def test_api_root_no_versions(api_root):
    set_api_root_response("""{
      "title": "Malware Research Group",
      "description": "A trust group setup for malware researchers",
      "max_content_length": 9765625
    }""")
    with pytest.raises(ValidationError) as excinfo:
        assert api_root._loaded_information is False
        api_root.refresh_information()

    assert "No 'versions' in API Root for request 'https://example.com/api1/'" == str(excinfo.value)


@responses.activate
def test_api_root_no_max_content_length(api_root):
    set_api_root_response("""{
      "title": "Malware Research Group",
      "description": "A trust group setup for malware researchers",
      "versions": ["taxii-2.0"]
    }""")
    with pytest.raises(ValidationError) as excinfo:
        assert api_root._loaded_information is False
        api_root.refresh_information()

    assert "No 'max_content_length' in API Root for request 'https://example.com/api1/'" == str(excinfo.value)


@responses.activate
def test_api_root(api_root):
    set_api_root_response(API_ROOT_RESPONSE)

    assert api_root._loaded_information is False
    assert api_root.title == "Malware Research Group"
    assert api_root._loaded_information is True
    assert api_root.description == "A trust group setup for malware researchers"
    assert api_root.versions == ["taxii-2.0"]
    assert api_root.max_content_length == 9765625

    apiroot_dict = json.loads(API_ROOT_RESPONSE)
    assert api_root._raw == apiroot_dict


@responses.activate
def test_api_root_collections(api_root):
    set_collections_response()

    assert api_root._loaded_collections is False
    assert len(api_root.collections) == 2
    assert api_root._loaded_collections is True

    coll = api_root.collections[0]
    # A collection populated from an API Root is automatically loaded
    assert coll._loaded is True
    assert coll.id == "91a7b528-80eb-42ed-a74d-c6fbd5a26116"
    assert coll.url == COLLECTION_URL
    assert coll.title == "High Value Indicator Collection"
    assert coll.description == "This data collection is for collecting high value IOCs"
    assert coll.can_read is True
    assert coll.can_write is False
    assert coll.media_types == [MEDIA_TYPE_STIX_V20]

    collection_dict = json.loads(COLLECTION_RESPONSE)
    assert coll._raw == collection_dict


@responses.activate
def test_collection(collection):
    assert collection._loaded is False
    assert collection.id == "91a7b528-80eb-42ed-a74d-c6fbd5a26116"
    assert collection._loaded is True
    assert collection.url == COLLECTION_URL
    assert collection.title == "High Value Indicator Collection"
    assert collection.description == "This data collection is for collecting high value IOCs"
    assert collection.can_read is True
    assert collection.can_write is False
    assert collection.media_types == [MEDIA_TYPE_STIX_V20]

    collection_dict = json.loads(COLLECTION_RESPONSE)
    assert collection._raw == collection_dict


def test_collection_unexpected_kwarg():
    with pytest.raises(TypeError):
        Collection(url="", conn=None, foo="bar")


@responses.activate
def test_get_collection_objects_paged_1(collection):
    obj_return = [json.loads(STIX_OBJECT) for _ in range(50)]
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[:10]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 0-9/50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[10:20]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 10-19/50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[20:30]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 20-29/50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[30:40]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 30-39/50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[40:50]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 40-49/50'})
    response = []

    for bundle in as_pages(collection.get_objects, per_request=10):
        response.extend(bundle.get("objects", []))

    assert len(response) == 50


@responses.activate
def test_get_collection_objects_paged_2(collection):
    obj_return = [json.loads(STIX_OBJECT) for _ in range(50)]
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[:10]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 0-9/*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[10:20]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 10-19/*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[20:30]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 20-29/*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[30:40]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 30-39/*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[40:50]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items 40-49/*'})
    responses.add(responses.GET, GET_OBJECTS_URL, "",
                  status=406, content_type=MEDIA_TYPE_STIX_V20)
    response = []

    # The status errors (any 400-500) will make it stop
    with pytest.raises(requests.exceptions.HTTPError):
        for bundle in as_pages(collection.get_objects, per_request=10):
            response.extend(bundle.get("objects", []))

    assert len(response) == 50


@responses.activate
def test_get_collection_objects_paged_3(collection):
    obj_return = [json.loads(STIX_OBJECT) for _ in range(50)]
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[:10]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[10:20]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[20:30]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[30:40]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */50'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[40:50]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */50'})
    response = []

    for bundle in as_pages(collection.get_objects, per_request=10):
        response.extend(bundle.get("objects", []))

    assert len(response) == 50


@responses.activate
def test_get_collection_objects_paged_4(collection):
    obj_return = [json.loads(STIX_OBJECT) for _ in range(50)]
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[:10]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[10:20]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[20:30]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[30:40]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */*'})
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[40:50]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20,
                  headers={'Content-Range': 'items */*'})
    responses.add(responses.GET, GET_OBJECTS_URL, "",
                  status=406, content_type=MEDIA_TYPE_STIX_V20)
    response = []

    # The status errors (any 400-500) will make it stop
    with pytest.raises(requests.exceptions.HTTPError):
        for bundle in as_pages(collection.get_objects, per_request=10):
            response.extend(bundle.get("objects", []))

    assert len(response) == 50


@responses.activate
def test_get_collection_objects_paged_5(collection):
    obj_return = [json.loads(STIX_OBJECT) for _ in range(50)]
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[:10]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20)
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[10:20]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20)
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[20:30]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20)
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[30:40]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20)
    responses.add(responses.GET, GET_OBJECTS_URL,
                  json.dumps({"type": "bundle", "spec_version": "2.0",
                              "id": "bundle--5d0092c5-5f74-4287-9642-33f4c354e56d",
                              "objects": obj_return[40:50]}),
                  status=200, content_type=MEDIA_TYPE_STIX_V20)
    responses.add(responses.GET, GET_OBJECTS_URL, "",
                  status=406, content_type=MEDIA_TYPE_STIX_V20)
    response = []

    # The status errors (any 400-500) will make it stop
    with pytest.raises(requests.exceptions.HTTPError):
        for bundle in as_pages(collection.get_objects, per_request=10):
            response.extend(bundle.get("objects", []))

    assert len(response) == 50


@responses.activate
def test_get_collection_objects(collection):
    responses.add(responses.GET, GET_OBJECTS_URL, GET_OBJECTS_RESPONSE,
                  status=200, content_type=MEDIA_TYPE_STIX_V20)

    response = collection.get_objects()

    assert response["spec_version"] == "2.0"
    assert len(response["objects"]) == 1


@responses.activate
def test_get_object(collection):
    responses.add(responses.GET, GET_OBJECT_URL, GET_OBJECT_RESPONSE,
                  status=200, content_type=MEDIA_TYPE_STIX_V20)

    response = collection.get_object("indicator--252c7c11-daf2-42bd-843b-be65edca9f61")
    indicator = response["objects"][0]
    assert indicator["id"] == "indicator--252c7c11-daf2-42bd-843b-be65edca9f61"


@responses.activate
def test_cannot_write_to_readonly_collection(collection):
    with pytest.raises(AccessError):
        collection.add_objects(STIX_BUNDLE)


@responses.activate
def test_add_object_to_collection(writable_collection):
    responses.add(responses.POST, ADD_WRITABLE_OBJECTS_URL,
                  ADD_OBJECTS_RESPONSE, status=202,
                  content_type=MEDIA_TYPE_TAXII_V20)

    status = writable_collection.add_objects(STIX_BUNDLE)

    assert status.status == "complete"
    assert status.total_count == 1
    assert status.success_count == 1
    assert len(status.successes) == 1
    assert status.failure_count == 0
    assert status.pending_count == 0

    status_dict = json.loads(ADD_OBJECTS_RESPONSE)
    assert status._raw == status_dict


@responses.activate
def test_add_object_to_collection_dict(writable_collection):
    responses.add(responses.POST, ADD_WRITABLE_OBJECTS_URL, ADD_OBJECTS_RESPONSE,
                  status=202, content_type=MEDIA_TYPE_TAXII_V20)

    dict_bundle = json.load(six.StringIO(STIX_BUNDLE))

    status = writable_collection.add_objects(dict_bundle)

    assert status.status == "complete"
    assert status.total_count == 1
    assert status.success_count == 1
    assert len(status.successes) == 1
    assert status.failure_count == 0
    assert status.pending_count == 0


@responses.activate
def test_add_object_to_collection_bin(writable_collection):
    responses.add(responses.POST, ADD_WRITABLE_OBJECTS_URL,
                  ADD_OBJECTS_RESPONSE, status=202,
                  content_type=MEDIA_TYPE_TAXII_V20)

    bin_bundle = STIX_BUNDLE.encode("utf-8")

    status = writable_collection.add_objects(bin_bundle)

    assert status.status == "complete"
    assert status.total_count == 1
    assert status.success_count == 1
    assert len(status.successes) == 1
    assert status.failure_count == 0
    assert status.pending_count == 0


@responses.activate
def test_add_object_to_collection_badtype(writable_collection):
    responses.add(responses.POST, ADD_WRITABLE_OBJECTS_URL,
                  ADD_OBJECTS_RESPONSE, status=202,
                  content_type=MEDIA_TYPE_TAXII_V20)

    with pytest.raises(TypeError):
        writable_collection.add_objects([1, 2, 3])


@responses.activate
def test_add_object_rases_error_when_collection_id_does_not_match_url(
        bad_writable_collection):
    responses.add(responses.POST, ADD_OBJECTS_URL, ADD_OBJECTS_RESPONSE,
                  status=202, content_type=MEDIA_TYPE_TAXII_V20)

    with pytest.raises(ValidationError) as excinfo:
        bad_writable_collection.add_objects(STIX_BUNDLE)

    msg = ("The collection 'e278b87e-0f9b-4c63-a34c-c8f0b3e91acb' does not "
           "match the url for queries "
           "'https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/'")

    assert str(excinfo.value) == msg


@responses.activate
def test_cannot_read_from_writeonly_collection(writable_collection):
    with pytest.raises(AccessError):
        writable_collection.get_objects()


@responses.activate
def test_get_manifest(collection):
    responses.add(responses.GET, MANIFEST_URL, GET_MANIFEST_RESPONSE,
                  status=200, content_type=MEDIA_TYPE_TAXII_V20)

    response = collection.get_manifest()

    assert len(response["objects"]) == 2
    obj = response["objects"][0]
    assert obj["id"] == "indicator--29aba82c-5393-42a8-9edb-6a2cb1df070b"
    assert len(obj["versions"]) == 2
    assert obj["media_types"][0] == MEDIA_TYPE_STIX_V20


@responses.activate
def test_get_status(api_root, status_dict):
    set_status_response()

    status = api_root.get_status(STATUS_ID)

    assert status.total_count == 4
    assert status.success_count == 1
    assert len(status.successes) == 1
    assert status.failure_count == 1
    assert len(status.failures) == 1
    assert status.pending_count == 2
    assert len(status.pendings) == 2

    assert status._raw == status_dict


@responses.activate
def test_status_raw(status_dict):
    """Test Status object created directly (not obtained via ApiRoot),
    and _raw property."""
    set_status_response()
    status = Status(STATUS_URL)
    assert status_dict == status._raw


@responses.activate
def test_content_type_valid(collection):
    responses.add(
        responses.GET,
        GET_OBJECT_URL,
        GET_OBJECT_RESPONSE,
        status=200,
        content_type=f"{MEDIA_TYPE_STIX_V20}; charset=utf-8",
    )


    response = collection.get_object("indicator--252c7c11-daf2-42bd-843b-be65edca9f61")
    indicator = response["objects"][0]
    assert indicator["id"] == "indicator--252c7c11-daf2-42bd-843b-be65edca9f61"


@responses.activate
def test_content_type_invalid(collection):
    responses.add(responses.GET, GET_OBJECT_URL, GET_OBJECT_RESPONSE,
                  status=200, content_type="taxii")

    with pytest.raises(TAXIIServiceException) as excinfo:
        collection.get_object("indicator--252c7c11-daf2-42bd-843b-be65edca9f61")
    assert ("Unexpected Response. Got Content-Type: 'taxii' for "
            "Accept: 'application/vnd.oasis.stix+json; version=2.0'") in str(excinfo.value)


def test_url_filter_type():
    params = _filter_kwargs_to_query_params({"type": "foo"})
    assert params == {"match[type]": "foo"}

    params = _filter_kwargs_to_query_params({"type": ("foo", "bar")})
    assert params == {"match[type]": "foo,bar"}


def test_filter_id():
    params = _filter_kwargs_to_query_params({"id": "foo"})
    assert params == {"match[id]": "foo"}

    params = _filter_kwargs_to_query_params({"id": ("foo", "bar")})
    assert params == {"match[id]": "foo,bar"}


def test_filter_version():
    params = _filter_kwargs_to_query_params({"version": "foo"})
    assert params == {"match[version]": "foo"}

    dt = datetime.datetime(2010, 9, 8, 7, 6, 5)
    params = _filter_kwargs_to_query_params({"version": dt})
    assert params == {"match[version]": "2010-09-08T07:06:05Z"}

    params = _filter_kwargs_to_query_params({"version": (dt, "bar")})
    assert params == {"match[version]": "2010-09-08T07:06:05Z,bar"}


def test_filter_added_after():
    params = _filter_kwargs_to_query_params({"added_after": "foo"})
    assert params == {"added_after": "foo"}

    dt = datetime.datetime(2010, 9, 8, 7, 6, 5)
    params = _filter_kwargs_to_query_params({"added_after": dt})
    assert params == {"added_after": "2010-09-08T07:06:05Z"}

    with pytest.raises(InvalidArgumentsError):
        _filter_kwargs_to_query_params({"added_after": (dt, "bar")})


def test_filter_combo():
    dt = datetime.datetime(2010, 9, 8, 7, 6, 5)
    params = _filter_kwargs_to_query_params({
        "added_after": dt,
        "type": ("indicator", "malware"),
        "version": dt,
        "foo": ("bar", "baz")
    })

    assert params == {
        "added_after": "2010-09-08T07:06:05Z",
        "match[type]": "indicator,malware",
        "match[version]": "2010-09-08T07:06:05Z",
        "match[foo]": "bar,baz"
    }


def test_params_filter_unknown():
    params = _filter_kwargs_to_query_params({"foo": "bar"})
    assert params == {"match[foo]": "bar"}


def test_taxii_endpoint_raises_exception():
    """Test exception is raised when conn and (user or pass) is provided"""
    conn = _HTTPConnection(user="foo", password="bar", verify=False)
    error_str = "Only one of a connection, username/password, or auth object may be provided."
    fake_url = "https://example.com/api1/collections/"

    with pytest.raises(InvalidArgumentsError) as excinfo:
        _TAXIIEndpoint(fake_url, conn, "other", "test")

    assert error_str in str(excinfo.value)

    with pytest.raises(InvalidArgumentsError) as excinfo:
        _TAXIIEndpoint(fake_url, conn, auth=TokenAuth('abcd'))

    assert error_str in str(excinfo.value)

    with pytest.raises(InvalidArgumentsError) as excinfo:
        _TAXIIEndpoint(fake_url, user="other", password="test", auth=TokenAuth('abcd'))

    assert error_str in str(excinfo.value)

    with pytest.raises(InvalidArgumentsError) as excinfo:
        _TAXIIEndpoint(fake_url, conn, "other", "test", auth=TokenAuth('abcd'))

    assert error_str in str(excinfo.value)


@responses.activate
def test_valid_content_type_for_connection():
    """The server responded with charset=utf-8, but the media types are correct
    and first."""
    responses.add(
        responses.GET,
        COLLECTION_URL,
        COLLECTIONS_RESPONSE,
        status=200,
        content_type=f"{MEDIA_TYPE_TAXII_V20}; charset=utf-8",
    )


    conn = _HTTPConnection(user="foo", password="bar", verify=False)
    conn.get("https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/",
             headers={"Accept": MEDIA_TYPE_TAXII_V20})


@responses.activate
def test_invalid_content_type_for_connection():
    responses.add(responses.GET, COLLECTION_URL, COLLECTIONS_RESPONSE,
                  status=200,
                  content_type=MEDIA_TYPE_TAXII_V20)

    with pytest.raises(TAXIIServiceException) as excinfo:
        conn = _HTTPConnection(user="foo", password="bar", verify=False)
        conn.get(
            "https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/",
            headers={"Accept": f"{MEDIA_TYPE_TAXII_V20}; charset=utf-8"},
        )


    assert ("Unexpected Response. Got Content-Type: 'application/vnd.oasis.taxii+json; "
            "version=2.0' for Accept: 'application/vnd.oasis.taxii+json; version=2.0; "
            "charset=utf-8'") in str(excinfo.value)


@responses.activate
def test_invalid_accept_for_connection():
    responses.add(responses.GET, COLLECTION_URL, COLLECTIONS_RESPONSE,
                  status=406, content_type=MEDIA_TYPE_TAXII_V20)

    with pytest.raises(requests.exceptions.HTTPError):
        conn = _HTTPConnection(user="foo", password="bar", verify=False)
        conn.get("https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/",
                 headers={"Accept": "application/taxii+json; version=2.1"})


def test_status_missing_id_property(status_dict):
    with pytest.raises(ValidationError) as excinfo:
        status_dict.pop("id")
        Status("https://example.com/api1/status/12345678-1234-1234-1234-123456789012/",
               user="foo", password="bar", verify=False,
               status_info=status_dict)

    assert "No 'id' in Status for request 'https://example.com/api1/status/12345678-1234-1234-1234-123456789012/'" == str(excinfo.value)


def test_status_missing_status_property(status_dict):
    with pytest.raises(ValidationError) as excinfo:
        status_dict.pop("status")
        Status("https://example.com/api1/status/12345678-1234-1234-1234-123456789012/",
               user="foo", password="bar", verify=False,
               status_info=status_dict)

    assert "No 'status' in Status for request 'https://example.com/api1/status/12345678-1234-1234-1234-123456789012/'" == str(excinfo.value)


def test_status_missing_total_count_property(status_dict):
    with pytest.raises(ValidationError) as excinfo:
        status_dict.pop("total_count")
        Status("https://example.com/api1/status/12345678-1234-1234-1234-123456789012/",
               user="foo", password="bar", verify=False,
               status_info=status_dict)

    assert "No 'total_count' in Status for request 'https://example.com/api1/status/12345678-1234-1234-1234-123456789012/'" == str(excinfo.value)


def test_status_missing_success_count_property(status_dict):
    with pytest.raises(ValidationError) as excinfo:
        status_dict.pop("success_count")
        Status("https://example.com/api1/status/12345678-1234-1234-1234-123456789012/",
               user="foo", password="bar", verify=False,
               status_info=status_dict)

    assert "No 'success_count' in Status for request 'https://example.com/api1/status/12345678-1234-1234-1234-123456789012/'" == str(excinfo.value)


def test_status_missing_failure_count_property(status_dict):
    with pytest.raises(ValidationError) as excinfo:
        status_dict.pop("failure_count")
        Status("https://example.com/api1/status/12345678-1234-1234-1234-123456789012/",
               user="foo", password="bar", verify=False,
               status_info=status_dict)

    assert "No 'failure_count' in Status for request 'https://example.com/api1/status/12345678-1234-1234-1234-123456789012/'" == str(excinfo.value)


def test_status_missing_pending_count_property(status_dict):
    with pytest.raises(ValidationError) as excinfo:
        status_dict.pop("pending_count")
        Status("https://example.com/api1/status/12345678-1234-1234-1234-123456789012/",
               user="foo", password="bar", verify=False,
               status_info=status_dict)

    assert "No 'pending_count' in Status for request 'https://example.com/api1/status/12345678-1234-1234-1234-123456789012/'" == str(excinfo.value)


def test_collection_missing_id_property(collection_dict):
    with pytest.raises(ValidationError) as excinfo:
        collection_dict.pop("id")
        Collection("https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/",
                   user="foo", password="bar", verify=False,
                   collection_info=collection_dict)

    assert "No 'id' in Collection for request 'https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/'" == str(excinfo.value)


def test_collection_missing_title_property(collection_dict):
    with pytest.raises(ValidationError) as excinfo:
        collection_dict.pop("title")
        Collection("https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/",
                   user="foo", password="bar", verify=False,
                   collection_info=collection_dict)

    assert "No 'title' in Collection for request 'https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/'" == str(excinfo.value)


def test_collection_missing_can_read_property(collection_dict):
    with pytest.raises(ValidationError) as excinfo:
        collection_dict.pop("can_read")
        Collection("https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/",
                   user="foo", password="bar", verify=False,
                   collection_info=collection_dict)

    assert "No 'can_read' in Collection for request 'https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/'" == str(excinfo.value)


def test_collection_missing_can_write_property(collection_dict):
    with pytest.raises(ValidationError) as excinfo:
        collection_dict.pop("can_write")
        Collection("https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/",
                   user="foo", password="bar", verify=False,
                   collection_info=collection_dict)

    assert "No 'can_write' in Collection for request 'https://example.com/api1/collections/91a7b528-80eb-42ed-a74d-c6fbd5a26116/'" == str(excinfo.value)


def test_conn_post_kwarg_errors():
    conn = _HTTPConnection()

    with pytest.raises(InvalidArgumentsError):
        conn.post(DISCOVERY_URL, data=1, json=2)

    with pytest.raises(InvalidArgumentsError):
        conn.post(DISCOVERY_URL, data=1, foo=2)

    with pytest.raises(InvalidArgumentsError):
        conn.post(DISCOVERY_URL, foo=1)


def test_user_agent_defaulting():
    conn = _HTTPConnection(user_agent="foo/1.0")
    headers = conn._merge_headers({})

    # also test key access is case-insensitive
    assert headers["user-agent"] == "foo/1.0"


def test_user_agent_overriding():
    conn = _HTTPConnection(user_agent="foo/1.0")
    headers = conn._merge_headers({"User-Agent": "bar/2.0"})

    assert headers["user-agent"] == "bar/2.0"


def test_user_agent_enforcing1():
    conn = _HTTPConnection(user_agent=None)
    headers = conn._merge_headers({})

    assert headers["user-agent"] == DEFAULT_USER_AGENT


def test_user_agent_enforcing2():
    conn = _HTTPConnection()
    headers = conn._merge_headers({"User-Agent": None})

    assert headers["user-agent"] == DEFAULT_USER_AGENT


def test_user_agent_enforcing3():
    conn = _HTTPConnection(user_agent=None)
    headers = conn._merge_headers({"User-Agent": None})

    assert headers["user-agent"] == DEFAULT_USER_AGENT


def test_header_merging():
    conn = _HTTPConnection()
    headers = conn._merge_headers({"AddedHeader": "addedvalue"})

    assert headers == {
        "user-agent": DEFAULT_USER_AGENT,
        "addedheader": "addedvalue"
    }


def test_header_merge_none():
    conn = _HTTPConnection()
    headers = conn._merge_headers(None)

    assert headers == {
        "user-agent": DEFAULT_USER_AGENT
    }


def test_collection_with_custom_properties(collection_dict):
    collection_dict["type"] = "domain"
    col_obj = Collection(url=WRITABLE_COLLECTION_URL, collection_info=collection_dict)
    assert len(col_obj.custom_properties) == 1
    assert col_obj.custom_properties["type"] == "domain"


def test_status_with_custom_properties(status_dict):
    status_dict["x_example_com"] = "some value"
    status_obj = Status(url=COLLECTION_URL, status_info=status_dict)
    assert len(status_obj.custom_properties) == 1
    assert status_obj.custom_properties["x_example_com"] == "some value"


@responses.activate
def test_api_roots_with_custom_properties(api_root):
    response = """{
      "title": "Malware Research Group",
      "description": "A trust group setup for malware researchers",
      "versions": ["taxii-2.0"],
      "max_content_length": 9765625,
      "x_example_com_total_items": 1000
    }"""
    set_api_root_response(response)
    api_root.refresh_information()
    assert len(api_root.custom_properties) == 1
    assert api_root.custom_properties["x_example_com_total_items"] == 1000


@responses.activate
def test_server_with_custom_properties(server):
    response = """{
      "title": "Some TAXII Server",
      "description": "This TAXII Server contains a listing of...",
      "contact": "string containing contact information",
      "default": "https://example.com/api2/",
      "api_roots": [
        "https://example.com/api1/",
        "https://example.com/api2/",
        "https://example.net/trustgroup1/"
      ],
      "x_example_com": "some value"
    }"""
    set_discovery_response(response)
    server.refresh()
    assert len(server.custom_properties) == 1
    assert server.custom_properties["x_example_com"] == "some value"


@responses.activate
def test_collection_missing_trailing_slash():
    set_collection_response()
    collection = Collection(COLLECTION_URL[:-1])
    responses.add(
        responses.GET,
        GET_OBJECT_URL,
        GET_OBJECT_RESPONSE,
        status=200,
        content_type=f"{MEDIA_TYPE_STIX_V20}; charset=utf-8",
    )


    response = collection.get_object("indicator--252c7c11-daf2-42bd-843b-be65edca9f61")
    indicator = response["objects"][0]
    assert indicator["id"] == "indicator--252c7c11-daf2-42bd-843b-be65edca9f61"


@responses.activate
def test_get_objects_pagination_success(collection):
    responses.add(responses.GET, GET_OBJECTS_URL, GET_OBJECTS_RESPONSE,
                  status=200, content_type=MEDIA_TYPE_STIX_V20)

    response = collection.get_objects(per_request=50).json()
    indicator = response["objects"][0]
    assert len(response["objects"]) == 1
    assert indicator["id"] == "indicator--252c7c11-daf2-42bd-843b-be65edca9f61"


@responses.activate
def test_get_objects_pagination_fail(collection):
    error = ERROR_MESSAGE % "400"
    responses.add(responses.GET, GET_OBJECTS_URL, error,
                  status=400, content_type=MEDIA_TYPE_STIX_V20)

    with pytest.raises(requests.exceptions.HTTPError) as e:
        collection.get_objects(per_request=50).json()

    assert e.value.response.status_code == 400


@responses.activate
def test_get_objects_pagination_fail_no_page(collection):
    error = ERROR_MESSAGE % "400"
    responses.add(responses.GET, GET_OBJECTS_URL, error,
                  status=400, content_type=MEDIA_TYPE_STIX_V20)

    with pytest.raises(requests.exceptions.HTTPError) as e:
        collection.get_objects().json()

    assert e.value.response.status_code == 400


@responses.activate
def test_get_manifests_pagination_success(collection):
    responses.add(responses.GET, MANIFEST_URL, GET_MANIFEST_RESPONSE,
                  status=200, content_type=MEDIA_TYPE_TAXII_V20)

    response = collection.get_manifest(per_request=50).json()
    assert len(response["objects"]) == 2
    obj = response["objects"][0]
    assert obj["id"] == "indicator--29aba82c-5393-42a8-9edb-6a2cb1df070b"
    assert len(obj["versions"]) == 2
    assert obj["media_types"][0] == MEDIA_TYPE_STIX_V20


@responses.activate
def test_get_manifests_pagination_fail(collection):
    error = ERROR_MESSAGE % "400"
    responses.add(responses.GET, MANIFEST_URL, error,
                  status=400, content_type=MEDIA_TYPE_TAXII_V20)

    with pytest.raises(requests.exceptions.HTTPError) as e:
        collection.get_manifest(per_request=50).json()

    assert e.value.response.status_code == 400


@responses.activate
def test_get_manifests_pagination_fail_no_page(collection):
    error = ERROR_MESSAGE % "400"
    responses.add(responses.GET, MANIFEST_URL, error,
                  status=400, content_type=MEDIA_TYPE_TAXII_V20)

    with pytest.raises(requests.exceptions.HTTPError) as e:
        collection.get_manifest().json()

    assert e.value.response.status_code == 400
