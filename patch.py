import os

# --- 1. config.py ---
cfg_path = 'config.py'
with open(cfg_path, 'r') as f:
    cfg = f.read()

cfg = cfg.replace("MODEL_PATH = \"yolov8n-face.pt\"", "MODEL_PATH = \"yolov8m.pt\"")
cfg = cfg.replace("MODEL_PATH = 'yolov8n-face.pt'", "MODEL_PATH = \"yolov8m.pt\"")
if "FALLBACK_MODEL_PATH" not in cfg:
    cfg = cfg.replace("MODEL_PATH = \"yolov8m.pt\"", "MODEL_PATH = \"yolov8m.pt\"\nFALLBACK_MODEL_PATH = \"yolov8n-face.pt\"")

with open(cfg_path, 'w') as f:
    f.write(cfg)


# --- 2. app.py ---
app_path = 'app.py'
with open(app_path, 'r') as f:
    app_src = f.read()

if "_shared_fallback_model =" not in app_src:
    app_src = app_src.replace(
        "_shared_model = YOLO(config.MODEL_PATH)",
        "_shared_model = YOLO(config.MODEL_PATH)\n_shared_fallback_model = YOLO(getattr(config, 'FALLBACK_MODEL_PATH', 'yolov8n-face.pt'))"
    )

app_src = app_src.replace(
    "job = VideoJob(job_id, save_path, file.filename, _shared_model,\n                    uploaded_by=current_user(), threshold=threshold)",
    "job = VideoJob(job_id, save_path, file.filename, _shared_model, fallback_model=_shared_fallback_model,\n                    uploaded_by=current_user(), threshold=threshold)"
)

with open(app_path, 'w') as f:
    f.write(app_src)

# --- 3. video_processor.py ---
vp_path = 'video_processor.py'
with open(vp_path, 'r') as f:
    vp = f.read()

# __init__
if "fallback_model: YOLO = None" not in vp:
    vp = vp.replace(
        "model: YOLO, bytetrack: bool = True, uploaded_by: str = \"Unknown\",",
        "model: YOLO, bytetrack: bool = True, uploaded_by: str = \"Unknown\", fallback_model: YOLO = None,"
    )
    vp = vp.replace(
        "self.model = model",
        "self.model = model\n        self.fallback_model = fallback_model"
    )

# _process
old_logic = '''            if run_detection:
                infer_start = time.time()
                if self.bytetrack:
                    results = self.model.track(
                        frame, persist=True, tracker=config.TRACKER_CFG,
                        classes=[config.PERSON_CLASS_ID], conf=config.CONFIDENCE_THRESHOLD,
                        iou=getattr(config, "IOU_THRESHOLD", 0.7),
                        imgsz=config.PROCESS_WIDTH or 1280,
                        verbose=False,
                    )[0]
                else:
                    results = self.model.predict(
                        frame, classes=[config.PERSON_CLASS_ID],
                        conf=config.CONFIDENCE_THRESHOLD,
                        iou=getattr(config, "IOU_THRESHOLD", 0.7),
                        imgsz=config.PROCESS_WIDTH or 1280,
                        verbose=False,
                    )[0]
                inference_ms = round((time.time() - infer_start) * 1000, 1)

                boxes = results.boxes
                person_count = len(boxes) if boxes is not None else 0
                box_coords = []
                centroids = []
                if boxes is not None:
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        box_coords.append((x1, y1, x2, y2))
                        centroids.append(((x1 + x2) // 2, (y1 + y2) // 2))
                self._last_boxes = box_coords
                self._last_count = person_count
                self._last_inference_ms = inference_ms'''

new_logic = '''            if run_detection:
                infer_start = time.time()
                if self.bytetrack:
                    results = self.model.track(
                        frame, persist=True, tracker=config.TRACKER_CFG,
                        classes=[config.PERSON_CLASS_ID], conf=config.CONFIDENCE_THRESHOLD,
                        iou=getattr(config, "IOU_THRESHOLD", 0.7),
                        imgsz=config.PROCESS_WIDTH or 1280,
                        verbose=False,
                    )[0]
                else:
                    results = self.model.predict(
                        frame, classes=[config.PERSON_CLASS_ID],
                        conf=config.CONFIDENCE_THRESHOLD,
                        iou=getattr(config, "IOU_THRESHOLD", 0.7),
                        imgsz=config.PROCESS_WIDTH or 1280,
                        verbose=False,
                    )[0]

                boxes = results.boxes
                box_coords = []
                centroids = []
                if boxes is not None:
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        box_coords.append((x1, y1, x2, y2))
                        centroids.append(((x1 + x2) // 2, (y1 + y2) // 2))

                # --- Fallback Head Detection ---
                if getattr(self, "fallback_model", None):
                    results_fb = self.fallback_model.predict(
                        frame, classes=[config.PERSON_CLASS_ID],
                        conf=config.CONFIDENCE_THRESHOLD,
                        iou=getattr(config, "IOU_THRESHOLD", 0.7),
                        imgsz=config.PROCESS_WIDTH or 1280,
                        verbose=False,
                    )[0]
                    boxes_fb = results_fb.boxes
                    if boxes_fb is not None:
                        for box in boxes_fb:
                            fx1, fy1, fx2, fy2 = map(int, box.xyxy[0])
                            fcx, fcy = (fx1 + fx2) // 2, (fy1 + fy2) // 2
                            # Check if head center is inside any primary body box
                            is_inside = False
                            for (px1, py1, px2, py2) in box_coords:
                                if px1 <= fcx <= px2 and py1 <= fcy <= py2:
                                    is_inside = True
                                    break
                            if not is_inside:
                                box_coords.append((fx1, fy1, fx2, fy2))
                                centroids.append((fcx, fcy))
                
                person_count = len(box_coords)
                inference_ms = round((time.time() - infer_start) * 1000, 1)
                self._last_boxes = box_coords
                self._last_count = person_count
                self._last_inference_ms = inference_ms'''

vp = vp.replace(old_logic, new_logic)

with open(vp_path, 'w') as f:
    f.write(vp)

print("Patching complete!")
