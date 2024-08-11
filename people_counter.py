import cv2
import argparse
import logging
from confluent_kafka import Producer
import numpy as np

# Load pre-trained object detection model (e.g., MobileNet SSD or YOLO)
model_path = "detector/MobileNetSSD_deploy.caffemodel"
prototxt_path = "detector/MobileNetSSD_deploy.prototxt"
net = cv2.dnn.readNetFromCaffe(prototxt_path, model_path)

# Specify the confidence threshold and the person class ID
CONFIDENCE_THRESHOLD = 0.4
PERSON_CLASS_ID = 15  # For MobileNet SSD, 15 is the class ID for 'person'


# Kafka producer configuration with SASL/SSL
def kafka_producer_config(broker, username, password):
    try:
        conf = {
            'bootstrap.servers': broker,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'PLAIN',
            'sasl.username': username,
            'sasl.password': password,
            'client.id': 'people_counting_client',
        }
        return Producer(**conf)
    except Exception as e:
        logging.error(f"Error setting up Kafka producer: {e}")
        return None


# Function to send data to Kafka
def send_to_kafka(producer, topic, key, value):
    try:
        producer.produce(topic, key=key, value=value)
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
def process_rtsp(rtsp_url, fps, kafka_producer=None, kafka_topic=None):
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        logging.error(f"Error opening RTSP stream: {rtsp_url}")
        return

    original_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_skip_interval = max(1, int(original_fps / fps))  # Calculate the number of frames to skip

    previous_centroids = []

    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    line_y = frame_height // 2  # Draw a line in the middle of the frame

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
                            send_to_kafka(kafka_producer, kafka_topic, key='people_count', value=1)
                    elif previous_centroid[1] > line_y and centroid[
                        1] <= line_y:  # Crossing the line from bottom to top
                        logging.info("Person left the area (-1).")
                        if kafka_producer and kafka_topic:
                            send_to_kafka(kafka_producer, kafka_topic, key='people_count', value=-1)

        previous_centroids = current_centroids

        cv2.imshow('Frame', frame)
        if cv2.waitKey(int(1000 / original_fps)) & 0xFF == ord('q'):
            logging.info("User interrupted the process.")
            break

    cap.release()
    cv2.destroyAllWindows()


def main(rtsp_urls, fps, kafka_broker, kafka_topic, kafka_username, kafka_password):
    kafka_producer = kafka_producer_config(kafka_broker, kafka_username, kafka_password)

    for rtsp_url in rtsp_urls:
        logging.info(f"Processing RTSP stream: {rtsp_url}")
        process_rtsp(rtsp_url, fps, kafka_producer, kafka_topic)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process RTSP streams and send people count changes to Kafka.')
    parser.add_argument('--rtsp_urls', nargs='+', required=True, help='List of RTSP URLs to process')
    parser.add_argument('--fps', type=int, default=30, help='Frames per second for processing')
    parser.add_argument('--kafka_broker', type=str, required=True, help='Kafka broker address')
    parser.add_argument('--kafka_topic', type=str, required=True, help='Kafka topic to send people count')
    parser.add_argument('--kafka_username', type=str, required=True, help='Kafka SASL username')
    parser.add_argument('--kafka_password', type=str, required=True, help='Kafka SASL password')
    args = parser.parse_args()

    main(args.rtsp_urls, args.fps, args.kafka_broker, args.kafka_topic, args.kafka_username, args.kafka_password)
