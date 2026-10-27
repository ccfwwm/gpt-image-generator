# image.aicodeme.xyz API and credential notes

Service documentation: [API docs](https://image.aicodeme.cn/docs/) (API version 7.9 at review time). Use the direct API base URL `https://image.aicodeme.xyz`.

## Credentials and billing groups

- Register at `https://image.aicodeme.xyz/signup/`, then create the key under 个人中心 → 开发者密钥 → 创建密钥. The secret is shown once; save it through the helper's local masked `configure-key` window, which the assistant opens itself (`references/setup-guide.md` has the four screenshots).
- Authenticate with `Authorization: Bearer <SK>`. Never put the key in chat, prompts, command arguments, logs, environment files, or package contents.
- `GET /v1/models` returns models available to the caller's key and its bound billing group. The group is chosen when creating the key; a per-request `billing_group_id` cannot override it. Do not add internal routing fields such as `upstream_pool_id`.
- The user confirmed that with the `image-低价分组` billing group **every model costs a flat ¥0.04 per image** (quota `0` means unlimited; quality and size do not change the price). Prices can still change, so re-check the site if a bill looks off.

## Models and quality

The user's confirmed model IDs are `gpt-image-2`, `gpt-image-2.5`, `gpt-image-2.5-sunburst`, and `gpt-image-2.5-flare`. The saved default is `gpt-image-2.5-sunburst`. The helper also accepts custom model IDs (for example, `gpt-image-2.5-sunburst-4k`) and passes them unchanged; availability is determined by the API and the key's group.

The saved default quality is `high`. The service documentation lists `low`, `medium`, `high`, `xhigh`, `max`, and `auto` for GPT Image 2.5 and says quality is passed through unchanged when no upstream mapping applies. This helper does not rewrite a requested quality; compatibility depends on the chosen model and group.

## Endpoints and request fields

| Operation | Endpoint | Request form |
| --- | --- | --- |
| List models | `GET /v1/models` | Bearer authorization |
| Generate | `POST /v1/images/generations` | JSON |
| Edit with local references | `POST /v1/images/edits` | Multipart form, repeated `image` file fields |

Generation fields used by the helper: `prompt`, `model`, `n`, `response_format`, `size`, `quality`, `background`, and `output_format`. Edit uses the same fields plus one or more image files. The helper accepts up to 16 local references, each at most 20 MB. The service also supports JSON URL/data references, but this helper intentionally uses local files for edit inputs.

The service currently documents a 3840 px maximum long edge, dimensions divisible by 16, aspect ratio up to 3:1, and a pixel count between 655,360 and 8,294,400. Confirm current limits in the service documentation if a request uses custom dimensions.

## Responses and errors

Successful synchronous responses can include `data[].b64_json` or `data[].url`; the helper saves either form. Explicit `response_format=b64_json` is the current default used by the helper. Pure text prompts use `generations`; any request with a reference image uses `edits`.

The helper redacts the configured key from upstream error text. Common responses include 401 for an invalid key and 429 for insufficient quota or a busy queue. Do not retry a paid generation automatically after a 429; explain the error and let the user choose whether to retry.

## Credential storage and transport

- Windows: the key is encrypted with the current Windows account using DPAPI and stored under the user's local application-data directory.
- macOS/Linux: the helper requires Python `keyring` with a supported native OS keychain backend: macOS Keychain, Linux Secret Service, or KWallet. It rejects null, plaintext, and other unapproved backends instead of writing the key to a file.
- On Windows, the helper prefers `curl.exe`; it sends the authorization header through curl's standard input configuration so the key is not in the process argument list. If curl is unavailable, Python HTTP is used. Edit mode on that fallback requires `requests`.
- Settings contain the selected model only; the key is never written to `settings.json`.
- Run `python scripts/aiimagesee_image.py configure-key` to open the masked setup window; it blocks until the user saves or cancels, then prints `dialog_result:` and `api_key:`. Use `--terminal` for hidden terminal input, `--detach` only when the host keeps detached children alive. The user can remove the saved credential later with `python scripts/aiimagesee_image.py clear-key`, which asks for confirmation and never displays the key.
- Popup prerequisites: a Python interpreter that can `import tkinter`. The helper checks itself first, then `gui_python` from settings, `py -3`, `python`/`pythonw` on PATH, and common install locations; the winner is saved as `gui_python` and shown by `config`. If none is found it raises a native message box instead of hanging.
