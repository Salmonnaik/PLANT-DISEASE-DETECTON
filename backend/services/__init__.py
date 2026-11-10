"""
Application services.

* ``ml_service``        - owns the loaded model and runs inference
* ``esp32_service``     - HTTP client and capture-job registry for the camera
* ``detection_service`` - the single image -> prediction -> database pipeline
* ``stats_service``     - aggregation queries for the dashboard and analytics

Deliberately import-free so that importing one service does not drag
TensorFlow or ``requests`` into a process that does not need them.
"""
