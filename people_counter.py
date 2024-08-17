import sys
import os
import cv2
import yaml
import logging
from confluent_kafka import Producer
import numpy as np
import json
import time

# Load pre-trained object detection model (e.g., MobileNet SSD or YOLO)
model_path = "detector/MobileNetSSD_deploy.caffemodel"
prototxt_path = "detector/MobileNetSSD_deploy.prototxt"
net = cv2.dnn.readNetFromCaffe(prototxt_path, model_path)

# Specify the confidence threshold and the person class ID
CONFIDENCE_THRESHOLD = 0.4
PERSON_CLASS_ID = 15  # For MobileNet SSD, 15 is the class ID for 'person'


# Kafka producer configuration with SASL/SSL
def kafka_producer_config(config):
    try:
        conf = {
            'bootstrap.servers': config['bootstrap_servers'],
            'security.protocol': config['security_protocol'],
            'sasl.mechanisms': config['sasl_mechanisms'],
            'sasl.username': config['sasl_username'],
            'sasl.password': config['sasl_password'],
            'client.id': 'people_counting_client'
            # 'debug': 'broker,topic,msg'
        }
        return Producer(**conf)
    except Exception as e:
        logging.error(f"Error setting up Kafka producer: {e}")
        return None


# Function to create the data according to Kafka Topic Schema
def build_kafka_message(camera_position, change):
    message = {
        #"cameraPosition": camera_position,
        #"timestamp": int(time.time()),
        "change": change
    }
    return json.dumps(message)


# Function to send data to Kafka
def send_to_kafka(producer, topic, position, change):
    try:
        message = build_kafka_message(position, change)
        producer.produce(topic, key=str(position).encode('utf-8'), value=message)
        producer.flush()
    except Exception as e:
        logging.error(f"Failed to send message to Kafka: {e}")


# Function to detect persons in a frame
def detect_persons(frame):
    (h, w) = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
    net.setInput(blob)
    detections = net.forward()

    centroids = []
    for i in range(detections.shape[2]):
        confidence = detections[0, 0, i, 2]
        if confidence > CONFIDENCE_THRESHOLD:
            class_id = int(detections[0, 0, i, 1])
            if class_id == PERSON_CLASS_ID:
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (startX, startY, endX, endY) = box.astype("int")
                centroid = (startX + endX) // 2, (startY + endY) // 2
                centroids.append(centroid)
                cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 255, 0), 2)

    return centroids


# Function to process a single RTSP stream
def process_rtsp(rtsp_url, fps, detection_line, kafka_producer=None, kafka_topic=None, position=None):
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        logging.error(f"Error opening RTSP stream: {rtsp_url}")
        return

    original_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_skip_interval = max(1, int(original_fps / fps))  # Calculate the number of frames to skip

    previous_centroids = []

    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    line_y = int(frame_height * detection_line)

    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            logging.info("End of RTSP stream reached or failed to read frame.")
            break

        frame_count += 1

        if frame_count % frame_skip_interval != 0:
            continue  # Skip the frame if it doesn't match the interval

        # Draw the line
        cv2.line(frame, (0, line_y), (frame_width, line_y), (0, 0, 255), 2)

        current_centroids = detect_persons(frame)
        for centroid in current_centroids:
            cv2.circle(frame, centroid, 5, (0, 255, 255), -1)
            for previous_centroid in previous_centroids:
                if abs(centroid[0] - previous_centroid[0]) < 50:  # Check if they are the same object
                    if previous_centroid[1] < line_y and centroid[1] >= line_y:  # Crossing the line from top to bottom
                        logging.info("Person entered the area (+1).")
                        if kafka_producer and kafka_topic:
                            send_to_kafka(kafka_producer, kafka_topic, position, change=1)
                    elif previous_centroid[1] > line_y and centroid[
                        1] <= line_y:  # Crossing the line from bottom to top
                        logging.info("Person left the area (-1).")
                        if kafka_producer and kafka_topic:
                            send_to_kafka(kafka_producer, kafka_topic, position, change=-1)

        previous_centroids = current_centroids

        # Optional: save frames or output to a file instead of displaying them
        # cv2.imwrite(f'/app/output/frame_{frame_count}.jpg', frame)

    cap.release()
    cv2.destroyAllWindows()


def main(camera_name=None):
    # Read config.yaml
    with open('config.yaml', 'r') as file:
        config = yaml.safe_load(file)

    logging.basicConfig(level=config['logging']['level'],
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[
                            logging.FileHandler(config['logging']['file']),
                            logging.StreamHandler()
                        ])

    kafka_producer = kafka_producer_config(config['kafka'])

    camera_config = None
    for camera in config['cameras']:
        if camera['name'] == camera_name:
            camera_config = camera
            break

    if camera_config is None:
        logging.error(f"No camera configuration found for camera: {camera_name}")
        return

    # Extract detection_line and fps from the specific camera's configuration
    fps = camera_config.get('fps', 15)
    detection_line = camera_config.get('detection_line', 0.5)
    camera_position = camera_config.get('camera_position', "no_position")

    logging.info(f"Processing RTSP stream from camera: {camera_config['name']}")
    process_rtsp(camera_config['rtsp_link'], fps, detection_line, kafka_producer,
                 camera_config['kafka_topic'], camera_position)


if __name__ == "__main__":
    camera_name = os.getenv("CAMERA_NAME")
    if not camera_name:
        print("CAMERA_NAME environment variable is not set.")
        sys.exit(1)
    main(camera_name)
