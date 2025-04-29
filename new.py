from flask import Flask, request, jsonify
import requests
import json
import os
import time
import random
from werkzeug.utils import secure_filename
import base64
from requests.exceptions import ConnectionError

OUTPUT_FOLDER = r"C:\Users\umakanths\Desktop\Comfy Api\output_images"
INPUT_FOLDER = r"C:\Users\umakanths\Desktop\Comfy Api\input"
COMFYUI_URL = "http://127.0.0.1:8188"

app = Flask(__name__, static_folder=OUTPUT_FOLDER, static_url_path=f'/{os.path.basename(OUTPUT_FOLDER)}')

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)
    print(f"Created output folder: {OUTPUT_FOLDER}")

if not os.path.exists(INPUT_FOLDER):
    os.makedirs(INPUT_FOLDER)
    print(f"Created input folder: {INPUT_FOLDER}")

def generate_random_digits(length=6):
    return ''.join(random.choice('0123456789') for _ in range(length))

def encode_to_base64(image_path):
    try:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            return encoded_string
    except Exception as e:
        print(f"Error encoding image to base64: {e}")
        return None

def safe_request(method, url, max_retries=5, delay=1, **kwargs):
    for i in range(max_retries):
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except ConnectionError as e:
            print(f"Connection error (attempt {i+1}/{max_retries}) to {url}: {e}")
            if i < max_retries - 1:
                time.sleep(delay * (i + 1))
            else:
                raise
        except requests.exceptions.RequestException as e:
            print(f"Request error (attempt {i+1}/{max_retries}) to {url}: {e}")
            if i < max_retries - 1:
                time.sleep(delay * (i + 1))
            else:
                raise


def upload_image_to_comfyui(image_data, filename):
    files = {"image": (filename, image_data, "image/jpeg")}
    try:
        response = safe_request("POST", f"{COMFYUI_URL}/upload/image", files=files)
        if response.status_code == 200:
            return filename
        else:
            print(f"Failed to upload image: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error during image upload: {e}")
        return None

def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": "python-api-"}
    data = json.dumps(p).encode('utf-8')
    try:
        response = safe_request("POST", f"{COMFYUI_URL}/prompt", data=data)
        if response.status_code == 200:
            response_data = response.json()
            print("Response from queue_prompt:", response_data)
            return response_data
        else:
            print(f"Failed to queue prompt. Status code: {response.status_code}")
            print("Response content:", response.text)
            return {}
    except requests.exceptions.RequestException as e:
        print(f"Error during prompt queuing: {e}")
        return {}

def get_image(filename, subfolder, folder_type):
    params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    print(f"get image data: {params}")
    try:
        response = safe_request("GET", f"{COMFYUI_URL}/view", params=params)
        if response.status_code == 200:
            print(f"get image response code: {response.status_code}")
            return response.content
        else:
            print(f"get image response code: {response.status_code}")
            print(f"get image response text: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error getting image: {e}")
        return None

def get_image_with_retry(filename, subfolder, folder_type, max_retries=3, retry_delay=1):
    for attempt in range(max_retries):
        image_data = get_image(filename, subfolder, folder_type)
        if image_data:
            return image_data
        print(f"Failed to get image, retrying (attempt {attempt + 1})...")
        time.sleep(retry_delay)
    return None

def wait_for_image(filepath, timeout=60, poll_interval=1):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return True
        time.sleep(poll_interval)
    return False

# Updated Upscale Workflow JSON
UPSCALE_WORKFLOW_JSON = {
    "1": {
        "inputs": {
            "model_name": "RealESRGAN_x4.pth"
        },
        "class_type": "UpscaleModelLoader",
        "_meta": {
            "title": "Load Upscale Model"
        }
    },
    "2": {
        "inputs": {
            "upscale_model": [
                "1",
                0
            ],
            "image": [
                "4",
                0
            ]
        },
        "class_type": "ImageUpscaleWithModel",
        "_meta": {
            "title": "Upscale Image (using Model)"
        }
    },
    "4": {
        "inputs": {
            "image": "input_image.png" # Placeholder, will be updated
        },
        "class_type": "LoadImage",
        "_meta": {
            "title": "Load Image"
        }
    },
    "7": {
        "inputs": {
            "upscale_method": "lanczos",
            "scale_by": 1.0000000000000002,
            "image": [
                "2",
                0
            ]
        },
        "class_type": "ImageScaleBy",
        "_meta": {
            "title": "Upscale Image By"
        }
    },
    "11": {
        "inputs": {
            "images": [
                "7",
                0
            ]
        },
        "class_type": "PreviewImage",
        "_meta": {
            "title": "Preview Image"
        }
    }
}

@app.route('/upscale_image', methods=['POST'])
def upscale_image():
    if 'image' not in request.files:
        return jsonify({"error": "Missing image file"}), 400

    input_image_file = request.files['image']
    input_filename_base = secure_filename(input_image_file.filename)
    random_suffix = generate_random_digits()
    input_filename = f"{os.path.splitext(input_filename_base)[0]}_{random_suffix}{os.path.splitext(input_filename_base)[1]}"
    input_path = os.path.join(INPUT_FOLDER, input_filename)

    try:
        input_image_file.save(input_path)
        print(f"Saved input image to {INPUT_FOLDER}")
    except Exception as e:
        print(f"Error saving input image: {e}")
        return jsonify({"error": f"Failed to save input image: {e}"}), 500

    uploaded_filename = upload_image_to_comfyui(open(input_path, 'rb').read(), os.path.basename(input_path))

    if not uploaded_filename:
        return jsonify({"error": "Failed to upload image to ComfyUI"}), 500

    workflow = UPSCALE_WORKFLOW_JSON.copy()
    workflow["4"]["inputs"]["image"] = uploaded_filename

    prompt_data = queue_prompt(workflow)
    if 'prompt_id' not in prompt_data:
        return jsonify({"error": "Failed to get prompt_id from the response", "response": prompt_data}), 500

    prompt_id = prompt_data['prompt_id']
    start_time = time.time()
    max_wait_time = 120

    while (time.time() - start_time) < max_wait_time:
        try:
            history_response = safe_request("GET", f"{COMFYUI_URL}/history/{prompt_id}")
            history = history_response.json()
            if prompt_id in history:
                if 'outputs' in history[prompt_id]:
                    outputs = history[prompt_id]['outputs']
                    print(f"Outputs: {json.dumps(outputs, indent=4)}")

                    # Get the upscaled image info from node ID 11
                    if "11" in outputs and "images" in outputs["11"] and outputs["11"]["images"]:
                        output_info = outputs["11"]["images"][0]
                        output_filename = output_info["filename"]
                        output_subfolder = output_info["subfolder"]
                        output_type = output_info["type"]  # Should be "temp"

                        image_data = get_image_with_retry(output_filename, output_subfolder, output_type)

                        if image_data:
                            # Encode the image data to Base64 directly
                            base64_encoded = base64.b64encode(image_data).decode('utf-8')
                            return jsonify({"output_image_base64": base64_encoded})
                        else:
                            return jsonify({"error": "Failed to retrieve upscaled image data from ComfyUI."}), 500
                time.sleep(1)
        except requests.exceptions.RequestException as e:
            print(f"Error while fetching history: {e}")
            time.sleep(1)

    return jsonify({"error": "Failed to generate upscaled image within the time limit."}, 500)

if __name__ == '__main__':
    app.run(debug=True, port=5003)










# from flask import Flask, request, jsonify, send_file
# import requests
# import json
# import os
# import time
# import random
# from werkzeug.utils import secure_filename
# from requests.exceptions import ConnectionError
# import io  # Import the io module

# OUTPUT_FOLDER = r"C:\Users\umakanths\Desktop\Comfy Api\output_images"
# INPUT_FOLDER = r"C:\Users\umakanths\Desktop\Comfy Api\input"
# COMFYUI_URL = "http://127.0.0.1:8188"

# app = Flask(__name__, static_folder=OUTPUT_FOLDER, static_url_path=f'/{os.path.basename(OUTPUT_FOLDER)}')

# if not os.path.exists(OUTPUT_FOLDER):
#     os.makedirs(OUTPUT_FOLDER)
#     print(f"Created output folder: {OUTPUT_FOLDER}")

# if not os.path.exists(INPUT_FOLDER):
#     os.makedirs(INPUT_FOLDER)
#     print(f"Created input folder: {INPUT_FOLDER}")

# def generate_random_digits(length=6):
#     return ''.join(random.choice('0123456789') for _ in range(length))

# def safe_request(method, url, max_retries=5, delay=1, **kwargs):
#     for i in range(max_retries):
#         try:
#             response = requests.request(method, url, **kwargs)
#             response.raise_for_status()
#             return response
#         except ConnectionError as e:
#             print(f"Connection error (attempt {i+1}/{max_retries}) to {url}: {e}")
#             if i < max_retries - 1:
#                 time.sleep(delay * (i + 1))
#             else:
#                 raise
#         except requests.exceptions.RequestException as e:
#             print(f"Request error (attempt {i+1}/{max_retries}) to {url}: {e}")
#             if i < max_retries - 1:
#                 time.sleep(delay * (i + 1))
#             else:
#                 raise

# # Function Definitions
# def upload_image_to_comfyui(image_data, filename):
#     files = {"image": (filename, image_data, "image/png")} # Assuming PNG for general compatibility
#     try:
#         response = safe_request("POST", f"{COMFYUI_URL}/upload/image", files=files)
#         if response.status_code == 200:
#             return filename
#         else:
#             print(f"Failed to upload image: {response.text}")
#             return None
#     except requests.exceptions.RequestException as e:
#         print(f"Error during image upload: {e}")
#         return None

# def queue_prompt(prompt):
#     p = {"prompt": prompt, "client_id": "python-api-"}
#     data = json.dumps(p).encode('utf-8')
#     try:
#         response = safe_request("POST", f"{COMFYUI_URL}/prompt", data=data)
#         if response.status_code == 200:
#             response_data = response.json()
#             print("Response from queue_prompt:", response_data)
#             return response_data
#         else:
#             print(f"Failed to queue prompt. Status code: {response.status_code}")
#             print("Response content:", response.text)
#             return {}
#     except requests.exceptions.RequestException as e:
#         print(f"Error during prompt queuing: {e}")
#         return {}

# def get_image(filename, subfolder, folder_type):
#     params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
#     print(f"get image data: {params}")
#     try:
#         response = safe_request("GET", f"{COMFYUI_URL}/view", params=params)
#         if response.status_code == 200:
#             print(f"get image response code: {response.status_code}")
#             return response.content
#         else:
#             print(f"get image response code: {response.status_code}")
#             print(f"get image response text: {response.text}")
#             return None
#     except requests.exceptions.RequestException as e:
#         print(f"Error getting image: {e}")
#         return None

# def get_image_with_retry(filename, subfolder, folder_type, max_retries=3, retry_delay=1):
#     for attempt in range(max_retries):
#         image_data = get_image(filename, subfolder, folder_type)
#         if image_data:
#             return image_data
#         print(f"Failed to get image, retrying (attempt {attempt + 1})...")
#         time.sleep(retry_delay)
#     return None

# def wait_for_image(filepath, timeout=60, poll_interval=1):
#     start_time = time.time()
#     while time.time() - start_time < timeout:
#         if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
#             return True
#         time.sleep(poll_interval)
#     return False

# # Updated Upscale Workflow JSON
# UPSCALE_WORKFLOW_JSON = {
#     "1": {
#         "inputs": {
#             "model_name": "RealESRGAN_x4.pth"
#         },
#         "class_type": "UpscaleModelLoader",
#         "_meta": {
#             "title": "Load Upscale Model"
#         }
#     },
#     "2": {
#         "inputs": {
#             "upscale_model": [
#                 "1",
#                 0
#             ],
#             "image": [
#                 "4",
#                 0
#             ]
#         },
#         "class_type": "ImageUpscaleWithModel",
#         "_meta": {
#             "title": "Upscale Image (using Model)"
#         }
#     },
#     "4": {
#         "inputs": {
#             "image": "input_image.png" # Placeholder, will be updated
#         },
#         "class_type": "LoadImage",
#         "_meta": {
#             "title": "Load Image"
#         }
#     },
#     "7": {
#         "inputs": {
#             "upscale_method": "lanczos",
#             "scale_by": 1.0000000000000002,
#             "image": [
#                 "2",
#                 0
#             ]
#         },
#         "class_type": "ImageScaleBy",
#         "_meta": {
#             "title": "Upscale Image By"
#         }
#     },
#     "11": {
#         "inputs": {
#             "images": [
#                 "7",
#                 0
#             ]
#         },
#         "class_type": "PreviewImage",
#         "_meta": {
#             "title": "Preview Image"
#         }
#     }
# }

# @app.route('/upscale_image', methods=['POST'])
# def upscale_image():
#     if 'image' not in request.files:
#         return jsonify({"error": "Missing image file"}), 400

#     input_image_file = request.files['image']
#     input_filename_base = secure_filename(input_image_file.filename)
#     random_suffix = generate_random_digits()
#     input_filename = f"{os.path.splitext(input_filename_base)[0]}_{random_suffix}{os.path.splitext(input_filename_base)[1]}"
#     input_path = os.path.join(INPUT_FOLDER, input_filename)

#     try:
#         input_image_file.save(input_path)
#         print(f"Saved input image to {INPUT_FOLDER}")
#     except Exception as e:
#         print(f"Error saving input image: {e}")
#         return jsonify({"error": f"Failed to save input image: {e}"}), 500

#     uploaded_filename = upload_image_to_comfyui(open(input_path, 'rb').read(), os.path.basename(input_path))

#     if not uploaded_filename:
#         return jsonify({"error": "Failed to upload image to ComfyUI"}), 500

#     workflow = UPSCALE_WORKFLOW_JSON.copy()
#     workflow["4"]["inputs"]["image"] = uploaded_filename

#     prompt_data = queue_prompt(workflow)
#     if 'prompt_id' not in prompt_data:
#         return jsonify({"error": "Failed to get prompt_id from the response", "response": prompt_data}), 500

#     prompt_id = prompt_data['prompt_id']
#     start_time = time.time()
#     max_wait_time = 120

#     while (time.time() - start_time) < max_wait_time:
#         try:
#             history_response = safe_request("GET", f"{COMFYUI_URL}/history/{prompt_id}")
#             history = history_response.json()
#             if prompt_id in history:
#                 if 'outputs' in history[prompt_id]:
#                     outputs = history[prompt_id]['outputs']
#                     print(f"Outputs: {json.dumps(outputs, indent=4)}")

#                     # Get the upscaled image info from node ID 11
#                     if "11" in outputs and "images" in outputs["11"] and outputs["11"]["images"]:
#                         output_info = outputs["11"]["images"][0]
#                         output_filename = output_info["filename"]
#                         output_subfolder = output_info["subfolder"]
#                         output_type = output_info["type"]

#                         image_data = get_image_with_retry(output_filename, output_subfolder, output_type)

#                         if image_data:
#                             return send_file(
#                                 io.BytesIO(image_data),
#                                 mimetype='image/png'  
#                             )
#                         else:
#                             return jsonify({"error": "Failed to retrieve upscaled image data from ComfyUI."}), 500
#                 time.sleep(1)
#         except requests.exceptions.RequestException as e:
#             print(f"Error while fetching history: {e}")
#             time.sleep(1)

#     return jsonify({"error": "Failed to generate upscaled image within the time limit."}, 500)

# if __name__ == '__main__':
#     app.run(debug=True, port=5003)