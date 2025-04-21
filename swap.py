from flask import Flask, request, jsonify
import requests
import json
import os
import time
import random
import shutil
from werkzeug.utils import secure_filename
import base64
from requests.exceptions import ConnectionError
 
OUTPUT_FOLDER = r"C:\Users\umakanths\Desktop\Test\output_images"
INPUT_FOLDER = r"C:\Users\umakanths\Desktop\Test\input"
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
 
# Function Definitions
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
 
# Workflow JSON
WORKFLOW_JSON = {
    "1": {
        "inputs": {"image": "person.jpg"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"}
    },
    "2": {
        "inputs": {"image": "cloth.jpg"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"}
    },
    "4": {
        "inputs": {
            "sam_model": "sam_vit_h (2.56GB)",
            "grounding_dino_model": "GroundingDINO_SwinT_OGC (694MB)",
            "threshold": 0.3,
            "detail_method": "VITMatte",
            "detail_erode": 6,
            "detail_dilate": 6,
            "black_point": 0.01,
            "white_point": 0.99,
            "process_detail": False,
            "prompt": "Swap the pant",
            "device": "cuda",
            "max_megapixels": 2,
            "cache_model": False,
            "image": ["1", 0]
        },
        "class_type": "LayerMask: SegmentAnythingUltra V2",
        "_meta": {"title": "LayerMask: SegmentAnythingUltra V2(Advance)"}
    },
    "5": {
        "inputs": {
            "mask_grow": 25,
            "mixed_precision": "fp16",
            "seed": 691583618472845,
            "steps": 40,
            "cfg": 2.5,
            "image": ["1", 0],
            "mask": ["4", 1],
            "refer_image": ["2", 0]
        },
        "class_type": "CatVTONWrapper",
        "_meta": {"title": "CatVTON Wrapper"}
    },
    "6": {
        "inputs": {"mask": ["4", 1]},
        "class_type": "LayerMask: MaskPreview",
        "_meta": {"title": "LayerMask: MaskPreview"}
    },
    "7": {
        "inputs": {"images": ["5", 0]},
        "class_type": "PreviewImage",
        "_meta": {"title": "Preview Image"}
    }
}
 
@app.route('/cloth_swap', methods=['POST'])
def cloth_swap():
    if 'person_image' not in request.files or 'cloth_image' not in request.files or 'prompt' not in request.form:
        return jsonify({"error": "Missing person_image, cloth_image, or prompt"}), 400
 
    person_image_file = request.files['person_image']
    cloth_image_file = request.files['cloth_image']
    prompt = request.form['prompt']
 
    person_filename_base = secure_filename(person_image_file.filename)
    cloth_filename_base = secure_filename(cloth_image_file.filename)
 
    random_suffix = generate_random_digits()
 
    person_input_filename = f"{os.path.splitext(person_filename_base)[0]}_{random_suffix}{os.path.splitext(person_filename_base)[1]}"
    cloth_input_filename = f"{os.path.splitext(cloth_filename_base)[0]}_{random_suffix}{os.path.splitext(cloth_filename_base)[1]}"
 
    person_input_path = os.path.join(INPUT_FOLDER, person_input_filename)
    cloth_input_path = os.path.join(INPUT_FOLDER, cloth_input_filename)
 
    try:
        person_image_file.save(person_input_path)
        cloth_image_file.save(cloth_input_path)
        print(f"Saved input images to {INPUT_FOLDER}")
    except Exception as e:
        print(f"Error saving input images: {e}")
        return jsonify({"error": f"Failed to save input images: {e}"}), 500
 
    uploaded_person_filename = upload_image_to_comfyui(open(person_input_path, 'rb').read(), os.path.basename(person_input_path))
    uploaded_cloth_filename = upload_image_to_comfyui(open(cloth_input_path, 'rb').read(), os.path.basename(cloth_input_path))
 
    if not uploaded_person_filename or not uploaded_cloth_filename:
        return jsonify({"error": "Failed to upload images to ComfyUI"}), 500
 
    workflow = WORKFLOW_JSON.copy()
    print("WORKFLOW: ", workflow)
 
    workflow["1"]["inputs"]["image"] = uploaded_person_filename
    workflow["2"]["inputs"]["image"] = uploaded_cloth_filename
    workflow["4"]["inputs"]["prompt"] = prompt
    workflow["5"]["inputs"]["seed"] = random.randint(0, 0xFFFFFFFFFFFFFFFF)
 
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
 
                    # Get the cloth swapped image (from node ID 7)
                    output_filename_cloth = outputs.get("7", {}).get("images", [{}])[0].get("filename")
                    cloth_image_data = get_image_with_retry(output_filename_cloth, "", "temp") if output_filename_cloth else None
 
                    # Get the mask image (from node ID 6)
                    output_filename_mask = outputs.get("6", {}).get("images", [{}])[0].get("filename")
                    mask_image_data = get_image_with_retry(output_filename_mask, "", "temp") if output_filename_mask else None
 
                    if cloth_image_data and mask_image_data:
                        try:
                            output_filename_cloth_with_suffix = f"{os.path.splitext(person_filename_base)[0]}_{random_suffix}_cloth.jpg"
                            output_filename_mask_with_suffix = f"{os.path.splitext(person_filename_base)[0]}_{random_suffix}_mask.jpg"
 
                            cloth_output_path = os.path.join(OUTPUT_FOLDER, output_filename_cloth_with_suffix)
                            mask_output_path = os.path.join(OUTPUT_FOLDER, output_filename_mask_with_suffix)
 
                            with open(cloth_output_path, "wb") as f:
                                f.write(cloth_image_data)
                            with open(mask_output_path, "wb") as f:
                                f.write(mask_image_data)
 
                            if wait_for_image(cloth_output_path) and wait_for_image(mask_output_path):
                                cloth_base64 = encode_to_base64(cloth_output_path)
                                mask_base64 = encode_to_base64(mask_output_path)
                                if cloth_base64 and mask_base64:
                                    return jsonify({
                                        "cloth_image_base64": cloth_base64,
                                        "mask_image_base64": mask_base64,
                                        "output_cloth_filename": output_filename_cloth_with_suffix,
                                        "output_mask_filename": output_filename_mask_with_suffix
                                    })
                                else:
                                    return jsonify({"error": "Failed to encode output images to base64."}), 500
                            else:
                                return jsonify({"error": "Image file was empty or not fully written."}), 500
 
                        except Exception as e:
                            print(f"Error saving image: {e}")
                            return jsonify({"error": "Failed to save image", "details": str(e)}), 500
                    else:
                        error_message = "Failed to retrieve image data."
                        if not cloth_image_data and not mask_image_data:
                            error_message = "Failed to retrieve both cloth and mask image data."
                        elif not cloth_image_data:
                            error_message = "Failed to retrieve cloth image data."
                        elif not mask_image_data:
                            error_message = "Failed to retrieve mask image data."
                        return jsonify({"error": error_message}), 500
                time.sleep(1)
        except requests.exceptions.RequestException as e:
            print(f"Error while fetching history: {e}")
            time.sleep(1)
 
    return jsonify({"error": "Failed to generate image within the time limit."}, 500)
 
if __name__ == '__main__':
    app.run(debug=True, port=5002)