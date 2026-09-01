with open('config.py', 'r') as f:
    content = f.read()
content = content.replace('yolov8m.pt', 'yolov8n-face.pt')
content = content.replace('\"yolov8n.pt\"', '\"yolov8n-face.pt\"')
content = content.replace('\'yolov8n.pt\'', '\'yolov8n-face.pt\'')
content = content.replace('CONFIDENCE_THRESHOLD = 0.05', 'CONFIDENCE_THRESHOLD = 0.25')
content = content.replace('CONFIDENCE_THRESHOLD = 0.4', 'CONFIDENCE_THRESHOLD = 0.25')
with open('config.py', 'w') as f:
    f.write(content)
print('Config updated')
