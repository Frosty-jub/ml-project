# หลักฐาน Training–serving parity

ทางเตรียมข้อมูลสำหรับเทรนและก่อนเรียก API ใช้ `build_features()` จาก
`src/demand_forecasting/features.py` ตัวเดียวกัน โดย `scripts/build_features.py`
ยังเปิดให้ import ชื่อเดิมได้ ตัวเตรียมคำขอเลือกฟีเจอร์ตาม feature manifest ของการเทรน
และส่งเฉพาะ `records` เข้า `POST /predict`; SKU และวันที่อยู่ในไฟล์ metadata แยก

## ความหมายของวันพยากรณ์

ระบบนี้พยากรณ์หลังปิดยอดขายของวัน `t` เพื่อทำนายยอดรวมวัน `t+1` ถึง `t+7`
`daily_sold_units` คือยอดของวัน `t`, `sales_lag_1` คือยอดวัน `t-1`
และ `sales_rolling_sum_7` รวมวัน `t-6` ถึง `t` การเรียกก่อนปิดยอดวัน `t`
ต้องใช้โมเดลและสัญญาฟีเจอร์สำหรับเวลานั้นโดยเฉพาะ

ใช้ `data/interim/sku_daily_sales.csv.gz` ที่สร้างจาก data pipeline ของทีม
โดยต้องมีประวัติทุกวันตั้งแต่วันขายแรกถึงวันพยากรณ์ รวมแถวที่ขายศูนย์ชิ้น
ตัวเตรียมจะปฏิเสธวันขาด วันซ้ำ ยอดที่ติดลบ/ไม่เป็นจำนวนเต็ม และประวัติไม่พอ
แถวหลังวันพยากรณ์และคอลัมน์ target จะไม่ถูกใช้สร้างคำขอ

ประวัติต้องเริ่มที่วันขายแรกจริง เพื่อให้ `days_since_first_sale` ตรงกับตอนเทรน
ตัวตรวจยืนยันว่าวันแรกมียอดขาย แต่ไม่สามารถพิสูจน์ว่าผู้ส่งไม่ได้ตัดประวัติเก่าที่เคยขายออก
จึงควรใช้ไฟล์ daily panel เดิมของ pipeline แทนการตัดเฉพาะ 28 วันล่าสุด

## เตรียมคำขอและเรียก API

รันจาก repository root หลังสร้างข้อมูลและ feature manifest และ export โมเดลของทีมแล้ว
ตัวอย่างนี้ใช้ SKU `85123A`, วัน `2011-09-01` และ bundle รุ่น 1; เปลี่ยนตามข้อมูลและรุ่นที่ใช้งานจริง
ไฟล์ history มี `sku_id`, `date` (หรือ `forecast_origin_date`) และ `daily_sold_units`

```powershell
python scripts/prepare_serving_request.py --origin 2011-09-01 --sku 85123A --output artifacts/serving_requests/request.json
```

คำสั่งนี้สร้าง `request.json` และ `request.metadata.json` ซึ่งมีลำดับ SKU/วันที่
และ checksum ของ history, pipeline config, manifest, feature code และ request
ตรวจว่า config ตรงกับ checksum ที่บันทึกใน manifest ก่อนสร้างฟีเจอร์
หากต้องการส่งไปยัง API ที่เปิดอยู่ เพิ่ม URL ฐาน:

```powershell
python scripts/prepare_serving_request.py --origin 2011-09-01 --sku 85123A --output artifacts/serving_requests/request.json --url http://127.0.0.1:18005
```

ก่อนส่งจะตรวจ `/schema` ว่าชื่อและลำดับฟีเจอร์ตรงกับ manifest และจำนวนรายการอยู่ใน batch limit
จากนั้นบันทึก `request.response.json` พร้อมชื่อ/รุ่นโมเดลที่ตอบกลับใน metadata
ใช้ `--sku` ซ้ำได้หลายครั้ง; หากจำนวน SKU เกิน batch limit ให้แบ่งคำขอเป็นชุด

## ตรวจโมเดลของทีมและเก็บหลักฐาน

```powershell
python scripts/verify_training_serving.py --origin 2011-09-01 --sku 85123A --model-dir serving/artifacts/group-v1-joblib --output reports/training_serving_parity/group-v1.json
```

คำสั่งสร้างฟีเจอร์จาก daily panel ผ่านทาง offline และทางเตรียมคำขอ
ตรวจทุกฟีเจอร์และลำดับคอลัมน์ แล้วเทียบผลทำนายโดยตรงกับผลจาก FastAPI TestClient
ซึ่งเรียกแอป API จริงภายใน process เพิ่ม `--url` เพื่อทดสอบผ่าน HTTP ของบริการที่เปิดอยู่:

```powershell
python scripts/verify_training_serving.py --origin 2011-09-01 --sku 85123A --model-dir serving/artifacts/group-v1-joblib --url http://127.0.0.1:18005 --output reports/training_serving_parity/group-v1-http.json
```

การตรวจ HTTP ยืนยันชื่อ/รุ่น/ชนิดข้อมูลและ checksum โมเดลตรงกับ local bundle
เกณฑ์ฟีเจอร์ต้องเท่ากันทุกค่า ผลทำนายต่างได้ไม่เกิน `1e-6` (`rtol=0`)
คำสั่งคืน exit code ไม่เป็นศูนย์เมื่อไม่ผ่าน และเขียน `status: failed` ทับหลักฐานเดิม
เพื่อไม่ให้ผลสำเร็จเก่าถูกเข้าใจว่าเป็นผลของรอบล่าสุด

## Automated tests และหลักฐานรอบนี้

```powershell
python -m unittest tests.test_serving_features -v
python -m pytest tests/test_serving_features.py -q
cd serving
python -m pytest tests -q
```

CI เดิมเรียก root unittest discovery และ serving pytest อยู่แล้ว จึงรวม tests ใหม่ทั้งสองส่วนอัตโนมัติ
ครอบคลุมการใช้ฟังก์ชันเดียวกัน ค่าที่คำนวณด้วยมือ การเรียง SKU/คอลัมน์ วันยอดศูนย์
วันที่เริ่มขายต่างกัน ข้อมูลอนาคต/target ประวัติไม่ครบ schema/config ไม่ตรง
การรันคำสั่งสร้าง request และผลทำนายผ่าน API ที่จัดลำดับ JSON keys ใหม่

ดู `reports/training_serving_parity/report_th.md` สำหรับผลทดสอบที่รันในเครื่องนี้
การพิสูจน์รอบนี้ใช้ข้อมูลสังเคราะห์และโมเดล LightGBM ที่ฝึกเพื่อทดสอบระบบ
ข้อมูลและโมเดลจริงของ Experiment 1–3 ไม่ได้อยู่ใน Git clone นี้ จึงต้องรันคำสั่งด้านบน
กับ bundle และ daily history จริงอีกครั้งก่อนใช้หลักฐานกับโมเดล production ของทีม

เครื่องมือ AI: ใช้ OpenAI Codex ช่วยย้ายฟังก์ชันร่วม สร้างตัวเตรียมคำขอ การตรวจ parity และ automated tests
