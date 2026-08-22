To expand your MCP server to expose all API endpoints from the provided OpenAPI specification as MCP tools, you'll need to:

1. Parse the OpenAPI JSON.
2. For each path and method (e.g., `POST /api/upload`, `GET /api/info`), generate a tool definition with:
   - A unique tool name (derived from `operationId` or path + method).
   - A description (from `summary` or `description`).
   - An input schema (JSON Schema) matching the endpoint’s path/query/body parameters.
3. Register these tools in your MCP server so they can be called by AI assistants.

Below is a Python solution using the official `mcp` SDK (`fastmcp` variant) and `httpx` to make HTTP requests. It dynamically reads the OpenAPI spec, generates tools, and handles file uploads by accepting base64-encoded file content from the MCP client (since MCP tools typically exchange JSON).

## Key Challenges & Solutions

- **Multipart/form-data requests**: The OpenAPI spec defines most POST endpoints with `multipart/form-data` containing a `file` field. MCP tools cannot directly send binary data; they receive JSON arguments. We solve this by having the tool accept a `file_base64` string (or file URL) and decode it to a temporary file before sending the HTTP request.
- **Path parameters**: e.g., `GET /api/audio/{session_id}`. These are included in the tool’s input schema as required fields.
- **Response handling**: The MCP tool should return the API’s JSON response (or a meaningful summary) as text/JSON.

## Step-by-Step Implementation

### 1. Load the OpenAPI spec
Read the JSON file (provided or hosted) into a Python dict.

### 2. Extract endpoint details
For each `path` and `method` in `spec["paths"]`:
- Collect path parameters from `parameters` list.
- If the request body is present, extract the schema reference to get the properties of the body.
- Merge all parameters into one flat input schema for the MCP tool.

### 3. Build MCP tool definitions
Use `FastMCP` from `mcp.server.fastmcp` to register a tool with a generated name, description, and JSON schema for arguments.

### 4. Implement the actual HTTP call
Inside each tool function:
- Decode base64 file data (if present) to a temporary file.
- Construct `multipart/form-data` or JSON request as needed.
- Send request via `httpx`.
- Return response JSON or text.

## Example Code (Python)

```python
import base64
import tempfile
import json
import httpx
from mcp.server.fastmcp import FastMCP
from typing import Any, Dict, Optional

# Load your OpenAPI spec (assume it's in the same directory as 'openapi.json')
with open("openapi.json", "r") as f:
    openapi_spec = json.load(f)

# Initialize MCP server
mcp = FastMCP("torchaudio-tools")

def resolve_schema_ref(ref: str, spec: dict) -> dict:
    """Resolve a $ref like '#/components/schemas/Body_upload...' to its schema."""
    parts = ref.strip("#/").split("/")
    current = spec
    for part in parts:
        current = current[part]
    return current

def generate_tool_name(operation_id: str, method: str, path: str) -> str:
    """Create a unique, snake_case tool name."""
    if operation_id:
        return operation_id
    # Fallback: method + path with special chars replaced
    name = f"{method.lower()}_{path.strip('/').replace('/', '_').replace('-', '_').replace('{', '').replace('}', '')}"
    return name

def build_input_schema(path_params: list, body_schema: Optional[dict]) -> dict:
    """Merge path parameters and body properties into a single JSON schema."""
    properties = {}
    required = []
    # Path parameters
    for param in path_params:
        name = param["name"]
        properties[name] = {
            "type": param["schema"].get("type", "string"),
            "description": param.get("description", ""),
        }
        if param.get("required", False):
            required.append(name)
    # Body properties (multipart/form-data or JSON)
    if body_schema and "properties" in body_schema:
        for prop_name, prop_schema in body_schema["properties"].items():
            # For file uploads, we'll accept base64 string
            if prop_schema.get("contentMediaType") == "application/octet-stream":
                properties[prop_name] = {
                    "type": "string",
                    "description": f"Base64-encoded content of {prop_name} (or a file URL).",
                    "format": "byte",
                }
            else:
                properties[prop_name] = {
                    "type": prop_schema.get("type", "string"),
                    "description": prop_schema.get("title", ""),
                }
                if "default" in prop_schema:
                    properties[prop_name]["default"] = prop_schema["default"]
                if prop_name in body_schema.get("required", []):
                    required.append(prop_name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }

# Iterate over all endpoints and register MCP tools
for path, methods in openapi_spec["paths"].items():
    for method, endpoint in methods.items():
        if method not in ["get", "post", "put", "delete", "patch"]:
            continue  # skip unsupported methods
        operation_id = endpoint.get("operationId", "")
        summary = endpoint.get("summary", "")
        description = endpoint.get("description", summary)
        path_params = endpoint.get("parameters", [])
        
        # Resolve request body schema if present
        body_schema = None
        request_body = endpoint.get("requestBody")
        if request_body:
            content = request_body.get("content", {})
            # Prefer multipart/form-data, fallback to application/json
            if "multipart/form-data" in content:
                schema_ref = content["multipart/form-data"]["schema"].get("$ref")
                if schema_ref:
                    body_schema = resolve_schema_ref(schema_ref, openapi_spec)
            elif "application/json" in content:
                schema_ref = content["application/json"]["schema"].get("$ref")
                if schema_ref:
                    body_schema = resolve_schema_ref(schema_ref, openapi_spec)
        
        input_schema = build_input_schema(path_params, body_schema)
        tool_name = generate_tool_name(operation_id, method, path)
        
        # Define the tool function with closure to capture endpoint details
        async def tool_func(args: Dict[str, Any] = None, 
                            _method=method, _path=path, _input_schema=input_schema, 
                            _body_schema=body_schema, _path_params=path_params) -> str:
            """Generic HTTP caller for the endpoint."""
            if args is None:
                args = {}
            # Separate path params from body params
            path_values = {}
            for param in _path_params:
                param_name = param["name"]
                if param_name in args:
                    path_values[param_name] = args[param_name]
            # Replace path placeholders like {session_id}
            full_url = _path.format(**path_values)
            
            # Prepare request
            files = {}
            data = {}
            json_data = None
            if _body_schema:
                for prop_name in _body_schema.get("properties", {}):
                    if prop_name in args:
                        value = args[prop_name]
                        # If the property is a file (base64), decode and add to files
                        if _body_schema["properties"][prop_name].get("contentMediaType") == "application/octet-stream":
                            # Decode base64 to temp file
                            try:
                                file_bytes = base64.b64decode(value)
                            except:
                                # Maybe it's a URL? Could download with httpx
                                async with httpx.AsyncClient() as client:
                                    resp = await client.get(value)
                                    resp.raise_for_status()
                                    file_bytes = resp.content
                            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                            tmp.write(file_bytes)
                            tmp.close()
                            files[prop_name] = (prop_name, open(tmp.name, "rb"))
                        else:
                            data[prop_name] = value
            # Make the HTTP request
            async with httpx.AsyncClient() as client:
                if files:
                    resp = await client.request(_method.upper(), full_url, files=files, data=data)
                elif data:
                    # If it's form data without files
                    resp = await client.request(_method.upper(), full_url, data=data)
                else:
                    resp = await client.request(_method.upper(), full_url, json=json_data)
            resp.raise_for_status()
            try:
                return json.dumps(resp.json(), indent=2)
            except:
                return resp.text
        
        # Register tool
        mcp.tool(name=tool_name, description=description, input_schema=input_schema)(tool_func)

if __name__ == "__main__":
    mcp.run()
```

## Important Notes

- **Base64 file handling**: The code assumes MCP clients will send `file` fields as base64-encoded strings. You can modify it to also accept URLs or local file paths if your use case requires.
- **Response format**: The tool returns the API’s JSON response as a string. You may want to extract only the relevant fields (e.g., download links) to reduce token usage.
- **Error handling**: The example uses `resp.raise_for_status()`. You may want to catch exceptions and return error messages.
- **Dynamic tool generation**: This script reads the OpenAPI spec at startup and registers all endpoints. For production, you might cache the schema or generate code ahead of time.
- **MCP SDK**: The code uses `mcp.server.fastmcp.FastMCP`. Install with `pip install mcp` and adjust imports if needed.
- **Authentication**: If the API requires auth, you’ll need to add headers or API keys in the tool functions.

## Alternative Approach: Use an Existing Generator

If you prefer not to write custom code, you can use tools like `openapi-to-mcp` (if available) or manually write a conversion script. The above solution gives you full control and handles the file upload challenge.

By following this pattern, you can expose every endpoint from the TorchAudio Processing Suite as an MCP tool, allowing AI assistants to upload audio, apply effects, run analyses, and more.

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "TorchAudio Processing Suite",
    "version": "1.0.0"
  },
  "paths": {
    "/api/upload": {
      "post": {
        "summary": "Upload Audio",
        "description": "Upload an audio file and return its info.",
        "operationId": "upload_audio_api_upload_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_upload_audio_api_upload_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/upload-session": {
      "post": {
        "summary": "Upload To Session",
        "description": "Upload audio and store in session for subsequent processing.",
        "operationId": "upload_to_session_api_upload_session_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_upload_to_session_api_upload_session_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/audio/{session_id}": {
      "get": {
        "summary": "Get Audio",
        "description": "Download the processed audio from a session.",
        "operationId": "get_audio_api_audio__session_id__get",
        "parameters": [
          {
            "name": "session_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Session Id"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/filter": {
      "post": {
        "summary": "Apply Filter",
        "description": "Apply a biquad filter to the audio.",
        "operationId": "apply_filter_api_filter_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_filter_api_filter_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/filter-chain": {
      "post": {
        "summary": "Apply Filter Chain",
        "description": "Apply a chain of filters.",
        "operationId": "apply_filter_chain_api_filter_chain_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_filter_chain_api_filter_chain_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/gain": {
      "post": {
        "summary": "Apply Gain",
        "description": "Apply gain in dB to audio.",
        "operationId": "apply_gain_api_effects_gain_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_gain_api_effects_gain_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/dither": {
      "post": {
        "summary": "Apply Dither",
        "description": "Apply dithering to audio.",
        "operationId": "apply_dither_api_effects_dither_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_dither_api_effects_dither_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/dcshift": {
      "post": {
        "summary": "Apply Dcshift",
        "description": "Apply DC shift to audio.",
        "operationId": "apply_dcshift_api_effects_dcshift_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_dcshift_api_effects_dcshift_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/overdrive": {
      "post": {
        "summary": "Apply Overdrive",
        "description": "Apply overdrive distortion.",
        "operationId": "apply_overdrive_api_effects_overdrive_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_overdrive_api_effects_overdrive_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/contrast": {
      "post": {
        "summary": "Apply Contrast",
        "description": "Apply contrast enhancement.",
        "operationId": "apply_contrast_api_effects_contrast_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_contrast_api_effects_contrast_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/flanger": {
      "post": {
        "summary": "Apply Flanger",
        "description": "Apply flanger effect.",
        "operationId": "apply_flanger_api_effects_flanger_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_flanger_api_effects_flanger_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/phaser": {
      "post": {
        "summary": "Apply Phaser",
        "description": "Apply phaser effect.",
        "operationId": "apply_phaser_api_effects_phaser_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_phaser_api_effects_phaser_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/pitch-shift": {
      "post": {
        "summary": "Pitch Shift",
        "description": "Shift the pitch of the audio by n_steps semitones.",
        "operationId": "pitch_shift_api_enhance_pitch_shift_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_pitch_shift_api_enhance_pitch_shift_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/speed": {
      "post": {
        "summary": "Change Speed",
        "description": "Change the speed of audio (also affects pitch).",
        "operationId": "change_speed_api_enhance_speed_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_change_speed_api_enhance_speed_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/preemphasis": {
      "post": {
        "summary": "Preemphasis",
        "description": "Apply pre-emphasis filter to boost high frequencies (enhance clarity).",
        "operationId": "preemphasis_api_enhance_preemphasis_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_preemphasis_api_enhance_preemphasis_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/deemphasis": {
      "post": {
        "summary": "Deemphasis",
        "description": "Apply de-emphasis filter.",
        "operationId": "deemphasis_api_enhance_deemphasis_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_deemphasis_api_enhance_deemphasis_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/volume": {
      "post": {
        "summary": "Change Volume",
        "description": "Change volume - amplitude multiplier or dB.",
        "operationId": "change_volume_api_enhance_volume_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_change_volume_api_enhance_volume_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/fade": {
      "post": {
        "summary": "Apply Fade",
        "description": "Apply fade in/out to audio (duration in seconds).",
        "operationId": "apply_fade_api_enhance_fade_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_fade_api_enhance_fade_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/add-noise": {
      "post": {
        "summary": "Add Noise",
        "description": "Add noise to audio at given SNR.",
        "operationId": "add_noise_api_enhance_add_noise_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_add_noise_api_enhance_add_noise_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/analysis/spectrogram": {
      "post": {
        "summary": "Compute Spectrogram",
        "description": "Compute spectrogram data for visualization.",
        "operationId": "compute_spectrogram_api_analysis_spectrogram_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_compute_spectrogram_api_analysis_spectrogram_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/analysis/mel-spectrogram": {
      "post": {
        "summary": "Compute Mel Spectrogram",
        "description": "Compute mel spectrogram.",
        "operationId": "compute_mel_spectrogram_api_analysis_mel_spectrogram_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_compute_mel_spectrogram_api_analysis_mel_spectrogram_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/analysis/mfcc": {
      "post": {
        "summary": "Compute Mfcc",
        "description": "Compute MFCC coefficients.",
        "operationId": "compute_mfcc_api_analysis_mfcc_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_compute_mfcc_api_analysis_mfcc_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/analysis/loudness": {
      "post": {
        "summary": "Compute Loudness",
        "description": "Compute loudness (ITU-R BS.1770-4 recommendation).",
        "operationId": "compute_loudness_api_analysis_loudness_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_compute_loudness_api_analysis_loudness_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/analysis/spectral-centroid": {
      "post": {
        "summary": "Compute Spectral Centroid",
        "description": "Compute spectral centroid.",
        "operationId": "compute_spectral_centroid_api_analysis_spectral_centroid_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_compute_spectral_centroid_api_analysis_spectral_centroid_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/analysis/pitch": {
      "post": {
        "summary": "Detect Pitch",
        "description": "Detect fundamental frequency (pitch) of audio.",
        "operationId": "detect_pitch_api_analysis_pitch_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_detect_pitch_api_analysis_pitch_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/separate": {
      "post": {
        "summary": "Separate Sources",
        "description": "Separate audio into sources using HDemucs.\nFor music: drums, bass, other, vocals\nModel sizes: low (fast), medium (balanced), high (best quality).",
        "operationId": "separate_sources_api_separate_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_separate_sources_api_separate_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/vad": {
      "post": {
        "summary": "Voice Activity Detection",
        "description": "Detect voice activity regions in audio.",
        "operationId": "voice_activity_detection_api_vad_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_voice_activity_detection_api_vad_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/resample": {
      "post": {
        "summary": "Resample Audio",
        "description": "Resample audio to target sample rate.",
        "operationId": "resample_audio_api_resample_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_resample_audio_api_resample_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/convolve": {
      "post": {
        "summary": "Apply Convolve",
        "description": "Apply convolution (useful for reverb simulation).",
        "operationId": "apply_convolve_api_effects_convolve_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_convolve_api_effects_convolve_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/effects/ir-convolve": {
      "post": {
        "summary": "Apply Ir Convolve",
        "description": "Convolve audio with a custom impulse response file.",
        "operationId": "apply_ir_convolve_api_effects_ir_convolve_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_apply_ir_convolve_api_effects_ir_convolve_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/enhance/time-stretch": {
      "post": {
        "summary": "Time Stretch",
        "description": "Time-stretch audio without changing pitch.",
        "operationId": "time_stretch_api_enhance_time_stretch_post",
        "requestBody": {
          "content": {
            "multipart/form-data": {
              "schema": {
                "$ref": "#/components/schemas/Body_time_stretch_api_enhance_time_stretch_post"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    },
    "/api/info": {
      "get": {
        "summary": "Get Info",
        "description": "Get information about available functionality.",
        "operationId": "get_info_api_info_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        }
      }
    },
    "/": {
      "get": {
        "summary": "Serve Frontend",
        "description": "Serve the main HTML application.",
        "operationId": "serve_frontend__get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {

                }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "Body_add_noise_api_enhance_add_noise_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "snr_db": {
            "type": "number",
            "title": "Snr Db",
            "default": 20
          },
          "noise_type": {
            "type": "string",
            "title": "Noise Type",
            "default": "gaussian"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_add_noise_api_enhance_add_noise_post"
      },
      "Body_apply_contrast_api_effects_contrast_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "enhancement_amount": {
            "type": "number",
            "title": "Enhancement Amount",
            "default": 75
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_contrast_api_effects_contrast_post"
      },
      "Body_apply_convolve_api_effects_convolve_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "mode": {
            "type": "string",
            "title": "Mode",
            "default": "full"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_convolve_api_effects_convolve_post"
      },
      "Body_apply_dcshift_api_effects_dcshift_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "shift": {
            "type": "number",
            "title": "Shift",
            "default": 0
          },
          "limiter_gain": {
            "type": "number",
            "title": "Limiter Gain",
            "default": 0
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_dcshift_api_effects_dcshift_post"
      },
      "Body_apply_dither_api_effects_dither_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "density_function": {
            "type": "string",
            "title": "Density Function",
            "default": "TPDF"
          },
          "noise_shaping": {
            "type": "boolean",
            "title": "Noise Shaping",
            "default": false
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_dither_api_effects_dither_post"
      },
      "Body_apply_fade_api_enhance_fade_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "fade_in": {
            "type": "number",
            "title": "Fade In",
            "default": 0
          },
          "fade_out": {
            "type": "number",
            "title": "Fade Out",
            "default": 0
          },
          "fade_shape": {
            "type": "string",
            "title": "Fade Shape",
            "default": "linear"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_fade_api_enhance_fade_post"
      },
      "Body_apply_filter_api_filter_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "filter_type": {
            "type": "string",
            "title": "Filter Type"
          },
          "cutoff_freq": {
            "type": "number",
            "title": "Cutoff Freq",
            "default": 1000
          },
          "Q": {
            "type": "number",
            "title": "Q",
            "default": 0.707
          },
          "gain_db": {
            "type": "number",
            "title": "Gain Db",
            "default": 0
          },
          "central_freq": {
            "type": "number",
            "title": "Central Freq",
            "default": 1000
          }
        },
        "type": "object",
        "required": [
          "file",
          "filter_type"
        ],
        "title": "Body_apply_filter_api_filter_post"
      },
      "Body_apply_filter_chain_api_filter_chain_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "filters": {
            "type": "string",
            "title": "Filters"
          }
        },
        "type": "object",
        "required": [
          "file",
          "filters"
        ],
        "title": "Body_apply_filter_chain_api_filter_chain_post"
      },
      "Body_apply_flanger_api_effects_flanger_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "delay": {
            "type": "number",
            "title": "Delay",
            "default": 0
          },
          "depth": {
            "type": "number",
            "title": "Depth",
            "default": 2
          },
          "regen": {
            "type": "number",
            "title": "Regen",
            "default": 0
          },
          "width": {
            "type": "number",
            "title": "Width",
            "default": 71
          },
          "speed": {
            "type": "number",
            "title": "Speed",
            "default": 0.5
          },
          "phase": {
            "type": "number",
            "title": "Phase",
            "default": 25
          },
          "modulation": {
            "type": "string",
            "title": "Modulation",
            "default": "sinusoidal"
          },
          "interpolation": {
            "type": "string",
            "title": "Interpolation",
            "default": "linear"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_flanger_api_effects_flanger_post"
      },
      "Body_apply_gain_api_effects_gain_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "gain_db": {
            "type": "number",
            "title": "Gain Db",
            "default": 0
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_gain_api_effects_gain_post"
      },
      "Body_apply_ir_convolve_api_effects_ir_convolve_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "ir_file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "Ir File"
          },
          "mode": {
            "type": "string",
            "title": "Mode",
            "default": "full"
          }
        },
        "type": "object",
        "required": [
          "file",
          "ir_file"
        ],
        "title": "Body_apply_ir_convolve_api_effects_ir_convolve_post"
      },
      "Body_apply_overdrive_api_effects_overdrive_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "gain": {
            "type": "number",
            "title": "Gain",
            "default": 20
          },
          "colour": {
            "type": "number",
            "title": "Colour",
            "default": 20
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_overdrive_api_effects_overdrive_post"
      },
      "Body_apply_phaser_api_effects_phaser_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "gain_in": {
            "type": "number",
            "title": "Gain In",
            "default": 0.4
          },
          "gain_out": {
            "type": "number",
            "title": "Gain Out",
            "default": 0.74
          },
          "delay_ms": {
            "type": "number",
            "title": "Delay Ms",
            "default": 3
          },
          "decay": {
            "type": "number",
            "title": "Decay",
            "default": 0.4
          },
          "mod_speed": {
            "type": "number",
            "title": "Mod Speed",
            "default": 0.5
          },
          "sinusoidal": {
            "type": "boolean",
            "title": "Sinusoidal",
            "default": true
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_apply_phaser_api_effects_phaser_post"
      },
      "Body_change_speed_api_enhance_speed_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "factor": {
            "type": "number",
            "title": "Factor",
            "default": 1
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_change_speed_api_enhance_speed_post"
      },
      "Body_change_volume_api_enhance_volume_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "gain_type": {
            "type": "string",
            "title": "Gain Type",
            "default": "amplitude"
          },
          "gain_value": {
            "type": "number",
            "title": "Gain Value",
            "default": 1
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_change_volume_api_enhance_volume_post"
      },
      "Body_compute_loudness_api_analysis_loudness_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_compute_loudness_api_analysis_loudness_post"
      },
      "Body_compute_mel_spectrogram_api_analysis_mel_spectrogram_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "n_fft": {
            "type": "integer",
            "title": "N Fft",
            "default": 400
          },
          "hop_length": {
            "type": "integer",
            "title": "Hop Length",
            "default": 160
          },
          "n_mels": {
            "type": "integer",
            "title": "N Mels",
            "default": 128
          },
          "to_db": {
            "type": "boolean",
            "title": "To Db",
            "default": true
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_compute_mel_spectrogram_api_analysis_mel_spectrogram_post"
      },
      "Body_compute_mfcc_api_analysis_mfcc_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "n_mfcc": {
            "type": "integer",
            "title": "N Mfcc",
            "default": 13
          },
          "n_mels": {
            "type": "integer",
            "title": "N Mels",
            "default": 40
          },
          "to_db": {
            "type": "boolean",
            "title": "To Db",
            "default": true
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_compute_mfcc_api_analysis_mfcc_post"
      },
      "Body_compute_spectral_centroid_api_analysis_spectral_centroid_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_compute_spectral_centroid_api_analysis_spectral_centroid_post"
      },
      "Body_compute_spectrogram_api_analysis_spectrogram_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "n_fft": {
            "type": "integer",
            "title": "N Fft",
            "default": 400
          },
          "hop_length": {
            "type": "integer",
            "title": "Hop Length",
            "default": 160
          },
          "power": {
            "type": "number",
            "title": "Power",
            "default": 2
          },
          "to_db": {
            "type": "boolean",
            "title": "To Db",
            "default": true
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_compute_spectrogram_api_analysis_spectrogram_post"
      },
      "Body_deemphasis_api_enhance_deemphasis_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "coeff": {
            "type": "number",
            "title": "Coeff",
            "default": 0.97
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_deemphasis_api_enhance_deemphasis_post"
      },
      "Body_detect_pitch_api_analysis_pitch_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "freq_low": {
            "type": "integer",
            "title": "Freq Low",
            "default": 85
          },
          "freq_high": {
            "type": "integer",
            "title": "Freq High",
            "default": 3400
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_detect_pitch_api_analysis_pitch_post"
      },
      "Body_pitch_shift_api_enhance_pitch_shift_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "n_steps": {
            "type": "number",
            "title": "N Steps",
            "default": 0
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_pitch_shift_api_enhance_pitch_shift_post"
      },
      "Body_preemphasis_api_enhance_preemphasis_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "coeff": {
            "type": "number",
            "title": "Coeff",
            "default": 0.97
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_preemphasis_api_enhance_preemphasis_post"
      },
      "Body_resample_audio_api_resample_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "target_sr": {
            "type": "integer",
            "title": "Target Sr",
            "default": 16000
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_resample_audio_api_resample_post"
      },
      "Body_separate_sources_api_separate_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "model_size": {
            "type": "string",
            "title": "Model Size",
            "default": "low"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_separate_sources_api_separate_post"
      },
      "Body_time_stretch_api_enhance_time_stretch_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "rate": {
            "type": "number",
            "title": "Rate",
            "default": 1
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_time_stretch_api_enhance_time_stretch_post"
      },
      "Body_upload_audio_api_upload_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_upload_audio_api_upload_post"
      },
      "Body_upload_to_session_api_upload_session_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "session_id": {
            "type": "string",
            "title": "Session Id",
            "default": "default"
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_upload_to_session_api_upload_session_post"
      },
      "Body_voice_activity_detection_api_vad_post": {
        "properties": {
          "file": {
            "type": "string",
            "contentMediaType": "application/octet-stream",
            "title": "File"
          },
          "trigger_level": {
            "type": "number",
            "title": "Trigger Level",
            "default": 7
          }
        },
        "type": "object",
        "required": [
          "file"
        ],
        "title": "Body_voice_activity_detection_api_vad_post"
      },
      "HTTPValidationError": {
        "properties": {
          "detail": {
            "items": {
              "$ref": "#/components/schemas/ValidationError"
            },
            "type": "array",
            "title": "Detail"
          }
        },
        "type": "object",
        "title": "HTTPValidationError"
      },
      "ValidationError": {
        "properties": {
          "loc": {
            "items": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "integer"
                }
              ]
            },
            "type": "array",
            "title": "Location"
          },
          "msg": {
            "type": "string",
            "title": "Message"
          },
          "type": {
            "type": "string",
            "title": "Error Type"
          },
          "input": {
            "title": "Input"
          },
          "ctx": {
            "type": "object",
            "title": "Context"
          }
        },
        "type": "object",
        "required": [
          "loc",
          "msg",
          "type"
        ],
        "title": "ValidationError"
      }
    }
  }
}
```