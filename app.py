from flask import Flask, request, jsonify
import requests
import json
import os
import time
import random
import shutil

app = Flask(__name__)

# ComfyUI server URL and output/input folder paths
COMFYUI_URL = "http://127.0.0.1:8188"
OUTPUT_FOLDER = r"C:\Users\umakanths\Desktop\Comfy\ComfyUI\output_images"
INPUT_FOLDER = r"C:\Users\umakanths\Desktop\Comfy\ComfyUI\input"
                           
# Function to delete the input folder before processing to ensure clean slate
def delete_input_folder():
    if os.path.exists(INPUT_FOLDER):
        try:
            shutil.rmtree(INPUT_FOLDER)  # Remove the entire directory tree
            print(f"Deleted folder: {INPUT_FOLDER}")
        except Exception as e:
            print(f"Failed to delete folder {INPUT_FOLDER}: {e}")
    else:
        print(f"Folder {INPUT_FOLDER} does not exist, skipping deletion.")

# Create the output folder if it doesn't exist
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)
    print(f"Created output folder: {OUTPUT_FOLDER}")

# Function to upload an image to ComfyUI
def upload_image_to_comfyui(image_data, filename):
    files = {"image": (filename, image_data, "image/jpeg")}  # Prepare the file data for upload
    response = requests.post(f"{COMFYUI_URL}/upload/image", files=files)  # Send the upload request
    if response.status_code == 200:
        return filename  # Return the filename if upload is successful
    else:
        print(f"Failed to upload image: {response.text}")
        return None

# Function to queue a prompt to ComfyUI
def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": "python-api-"}  # Prepare the prompt data
    data = json.dumps(p).encode('utf-8')  # Encode the data as JSON
    req = requests.post(url=f"{COMFYUI_URL}/prompt", data=data)  # Send the prompt request
    
    if req.status_code != 200:
        print(f"Failed to queue prompt. Status code: {req.status_code}")
        print("Response content:", req.text)
        return {}  # Return an empty dictionary if the request fails
    
    response_data = req.json()  # Parse the JSON response
    print("Response from queue_prompt:", response_data)
    return response_data

# Function to retrieve an image from ComfyUI
def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}  # Prepare the image retrieval data
    print(f"get image data: {data}")
    response = requests.get(f"{COMFYUI_URL}/view", params=data)  # Send the image retrieval request
    print(f"get image response code: {response.status_code}")
    if response.status_code != 200:
        print(f"get image response text: {response.text}")
    return response.content  # Return the image content

# Function to retrieve an image with retry logic
def get_image_with_retry(filename, subfolder, folder_type, max_retries=3, retry_delay=1):
    for attempt in range(max_retries):
        image_data = get_image(filename, subfolder, folder_type)  # Attempt to retrieve the image
        if image_data:
            return image_data  # Return the image if successful
        print(f"Failed to get image, retrying (attempt {attempt + 1})...")
        time.sleep(retry_delay)  # Wait before retrying
    return None

# Function to wait for an image file to be created and populated
def wait_for_image(filepath, timeout=60, poll_interval=1):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return True  # Return True if the file exists and is not empty
        time.sleep(poll_interval)  # Wait before checking again
    return False

# Workflow JSON for ComfyUI
WORKFLOW_JSON = {
    "1": {
        "inputs": {"image": "women.JPG"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"}
    },
    "2": {
        "inputs": {"image": "women dress.JPG"},
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

# Flask route for cloth swapping
@app.route('/cloth_swap', methods=['POST'])
def cloth_swap():
    delete_input_folder()  # Delete the input folder before processing

    # Check if required files and form data are present
    if 'person_image' not in request.files or 'cloth_image' not in request.files or 'prompt' not in request.form:
        return jsonify({"error": "Missing person_image, cloth_image, or prompt"}), 400

    person_image = request.files['person_image'].read()  # Read the person image data
    cloth_image = request.files['cloth_image'].read()  # Read the cloth image data
    prompt = request.form['prompt']  # Read the prompt

    person_filename = upload_image_to_comfyui(person_image, "person.jpg")  # Upload the person image
    cloth_filename = upload_image_to_comfyui(cloth_image, "cloth.jpg")  # Upload the cloth image

    # Check if image uploads were successful
    if not person_filename or not cloth_filename:
        return jsonify({"error": "Failed to upload images to ComfyUI"}), 500

    workflow = WORKFLOW_JSON.copy()  # Create a copy of the workflow
    print("WORKFLOW: ", workflow)

    # Update the workflow with the uploaded image filenames and the prompt
    workflow["1"]["inputs"]["image"] = person_filename
    workflow["2"]["inputs"]["image"] = cloth_filename
    workflow["4"]["inputs"]["prompt"] = prompt
    workflow["5"]["inputs"]["seed"] = random.randint(0, 0xFFFFFFFFFFFFFFFF) #random seed

    prompt_data = queue_prompt(workflow)  # Queue the prompt to ComfyUI

    # Check if prompt_id is present in the response
    if 'prompt_id' not in prompt_data:
        return jsonify({"error": "Failed to get prompt_id from the response", "response": prompt_data}), 500

    prompt_id = prompt_data['prompt_id']  # Get the prompt ID
    start_time = time.time()
    max_wait_time = 120  # Maximum wait time in seconds

    # Wait for the ComfyUI processing to complete
    while (time.time() - start_time) < max_wait_time:
        history = requests.get(f"{COMFYUI_URL}/history/{prompt_id}").json()  # Get the processing history
        if prompt_id in history:
            if 'outputs' in history[prompt_id]:
                outputs = history[prompt_id]['outputs']
                print(f"Outputs: {json.dumps(outputs, indent=4)}")

                # Get the cloth swapped image (from node ID 7)
                if "7" in outputs and "images" in outputs["7"]:
                    output_filename_cloth = outputs["7"]["images"][0]["filename"]
                    cloth_image_data = get_image_with_retry(output_filename_cloth, "", "temp")
                else:
                    return jsonify({"error": "Cloth swapped image output not found."}, 500)

                # Get the mask image (from node ID 6)
                if "6" in outputs and "images" in outputs["6"]:
                    output_filename_mask = outputs["6"]["images"][0]["filename"]
                    mask_image_data = get_image_with_retry(output_filename_mask, "", "temp")
                else:
                    return jsonify({"error": "MaskPreview node output not found."}, 500)

                # Save the images to the output folder
                if cloth_image_data and mask_image_data:
                    try:
                        cloth_path = os.path.join(OUTPUT_FOLDER, f"{prompt_id}_cloth.jpg")
                        mask_path = os.path.join(OUTPUT_FOLDER, f"{prompt_id}_mask.jpg")

                        with open(cloth_path, "wb") as f:
                            f.write(cloth_image_data)
                        with open(mask_path, "wb") as f:
                            f.write(mask_image_data)

                        # Wait for the images to be fully written
                        if wait_for_image(cloth_path) and wait_for_image(mask_path):
                            cloth_url = f"http://127.0.0.1:5001/{os.path.basename(OUTPUT_FOLDER)}/{prompt_id}_cloth.jpg"
                            mask_url = f"http://127.0.0.1:5001/{os.path.basename(OUTPUT_FOLDER)}/{prompt_id}_mask.jpg"
                            return jsonify({"cloth_image_url": cloth_url, "mask_image_url": mask_url})
                        else:
                            return jsonify({"error": "Image file was empty or not fully written."}), 500

                    except Exception as e:
                        print(f"Error saving image: {e}")
                        return jsonify({"error": "Failed to save image", "details": str(e)}), 500
                else:
                    return jsonify({"error": "Failed to retrieve image data."}, 500)

        time.sleep(1)  # Wait for 1 second before checking again

    return jsonify({"error": "Failed to generate image within the time limit."}, 500)

# Flask route to serve the output images
@app.route(f"/{os.path.basename(OUTPUT_FOLDER)}/<path:filename>")
def serve_output_image(filename):
    return app.send_static_file(os.path.join(OUTPUT_FOLDER, filename))

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True, port=5001)