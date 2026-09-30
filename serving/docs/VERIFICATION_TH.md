# หลักฐานทดสอบส่วน Model Serving

## ตรวจชุดสำหรับ repository กลุ่ม

ก่อน push ไป branch `GG` วางชุดนี้ใน `serving/` และปรับให้ Docker สร้างโมเดลสาธิตตอน build โดยไม่เก็บ binary ใน Git ทดสอบ pytest ผ่าน 21 กรณี (`reports/repository_test_results.xml`), Ruff ผ่าน, Docker build จาก source สำเร็จและ health check ผ่าน พร้อมทดสอบ HTTP จริงครบ 7 checks ที่พอร์ต 18006 (`reports/repository_http_evidence.json`) ส่วนเดโมเดิมที่พอร์ต 18005 ยังคงทำงาน ผล load test ด้านล่างเป็นหลักฐานจากชุด standalone ก่อนปรับการจัดแพ็กเกจ

ทดสอบจริงวันที่ 28 กันยายน 2569 (เวลาไทย) บน Windows 11 / Python 3.13.9 และ Docker Desktop Linux engine 29.6.1 ใช้โมเดล `synthetic-demand-demo`, เวอร์ชัน `demo-v1` จากข้อมูลสังเคราะห์เท่านั้น

## ความถูกต้อง

- pytest ผ่าน 21 กรณี รวมข้อมูลปกติ, null ที่อนุญาต, ฟีเจอร์หาย/เกิน, ชนิดผิด, NaN/Infinity, JSON เสีย, batch เกิน, โมเดลไม่พร้อม, checksum ผิด, inference failure, request ID และ metrics
- ผล API ตรงกับ fitted Pipeline โดยตรง แม้ลำดับ key ใน JSON เปลี่ยนไป
- Ruff ตรวจโค้ดผ่าน และ pip check ไม่พบ dependencies ขัดแย้ง
- มี deprecation warning หนึ่งรายการจาก Starlette TestClient ซึ่งยังใช้ httpx ได้ในเวอร์ชันที่ตรึงไว้ ไม่ใช่ test failure
- Docker build สำเร็จ และคอนเทนเนอร์มีสถานะ healthy
- เรียก HTTP จริงผ่าน `/health`, `/schema`, `/openapi.json`, `/predict` กรณีปกติ/null/ข้อมูลเสีย และ `/metrics` ผ่านครบ 7 checks ข้อมูลเสียตอบ 422 ก่อนเข้าโมเดล

หลักฐาน: `reports/test_results.xml`, `reports/http_evidence_docker.json`, `reports/http_evidence_docker.prom`, `reports/environment.json`, `reports/docker_logs.txt`

## ประสิทธิภาพ

เงื่อนไขเหมือนกันทั้งก่อนและหลัง: 500 HTTP requests, concurrency 10, หนึ่ง record ต่อ request, warmup 20 ครั้งไม่นับผล, connection keep-alive และวัดจาก client บน Windows ไปยัง API ใน Docker ผ่าน localhost:18005

| ตัวชี้วัด | SLO ที่ประกาศก่อนทดสอบ | ก่อนปรับ | หลังปรับ |
|---|---:|---:|---:|
| p50 latency | ≤ 100 ms | 125.09 ms — ไม่ผ่าน | 92.37 ms — ผ่าน |
| p95 latency | ≤ 250 ms | 171.68 ms — ผ่าน | 131.27 ms — ผ่าน |
| Successful throughput | ≥ 20 requests/s | 79.22 requests/s — ผ่าน | 106.48 requests/s — ผ่าน |
| Error rate | ≤ 1% | 0% — ผ่าน | 0% — ผ่าน |
| SLO รวม | ผ่านทุกเกณฑ์ | ไม่ผ่าน | ผ่าน |

การปรับ: สร้าง DataFrame ตัวเลขพร้อม dtype ครั้งเดียว ลดการสร้าง/แปลงคอลัมน์ซ้ำ และจำกัด inference ให้ทำงานทีละคำขอด้วย lock เพื่อลด CPU contention ไม่เปลี่ยนโมเดล ไม่เปลี่ยนเกณฑ์ SLO และไม่มี prediction cache หลังปรับรัน pytest ใหม่ผ่าน 21 กรณี แล้ว rebuild คอนเทนเนอร์และวัด HTTP อีกครั้ง

ผลดิบ: `reports/load_test_docker_before.json` และ `reports/load_test_docker.json` เก็บผล Windows local ก่อนปรับแยกไว้ใน `reports/load_test_local.json` ซึ่งเป็น baseline ของโค้ดรอบแรก

ข้อมูลนี้เป็นช่วงทดสอบสั้นบนเครื่องนี้เท่านั้น ไม่ยืนยัน availability ระยะยาว, performance บนเครื่องอื่น หรือ performance ของโมเดลจริงของกลุ่ม ต้องเปลี่ยนโมเดลจริง ยืนยัน SLO กับทีม และรันทดสอบใหม่ก่อนส่งโครงงาน

## สิ่งที่ต้องทำร่วมกับกลุ่มก่อนส่งฉบับสุดท้าย

1. เชื่อมโมเดลที่สมาชิกฝึกและ Registry อนุมัติแล้ว พร้อม schema จริง โดยใช้ `scripts/export_model.py`
2. ให้คนที่ 1 ส่งฟีเจอร์ด้วยโค้ดร่วมสำหรับ train/serving โดยเฉพาะ lag และ rolling
3. ให้คนที่ 5 เชื่อม `/metrics`, logs และข้อมูลที่ต้องใช้สำหรับ drift/ground truth
4. ให้คนที่ 6 รวม compose และ CI/CD ของกลุ่ม ทดสอบ end-to-end และบันทึก branch/commit/PR จริง
5. ใช้ผลทดสอบของโมเดลจริงและระบุส่วนที่ใช้ AI ช่วยในรายงาน
