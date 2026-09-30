# ส่งต่องานให้สมาชิกในกลุ่ม

## สิ่งที่เตรียมไว้แล้ว

- เลือก UCI Online Retail II พร้อมลิงก์ต้นทาง การอ้างอิง และใบอนุญาต
- กำหนดหน่วยพยากรณ์เป็น SKU ต่อวัน และ target เป็นยอดขายรวมเจ็ดวันถัดไป
- เตรียมสคริปต์ดาวน์โหลดและแปลง workbook เป็นตารางรายวัน
- ดาวน์โหลดและแปลง dataset จริงในเครื่องแล้ว พร้อมบันทึกจำนวนแถวและ checksum ที่ `docs/data_intake.md`
- แยกข้อมูลดิบและไฟล์ที่สร้างออกจาก Git
- วางพื้นที่สำหรับ data, docs, notebooks, reports, code และ model artifacts
- เพิ่ม EDA, กฎ clean ที่บันทึกเหตุผล, Data Validation, time split และ lag/rolling/calendar features; ดู [`data_pipeline_feature_engineering.md`](data_pipeline_feature_engineering.md)

## งานถัดไปที่ทีมควรทำตามลำดับ

1. วางไฟล์ข้อกำหนดรายวิชาไว้ใน `docs/` แล้วสร้าง checklist ส่งงาน/เกณฑ์ประเมินจากเอกสารจริง
2. ทุกคนสร้างข้อมูลซ้ำด้วย `python scripts/run_data_pipeline.py` แล้วอ่าน Data Validation/manifest ใน `reports/generated/` และ [`รายงาน EDA`](../reports/eda_summary.md)
3. ทีมทบทวนกฎคัดรหัสที่ไม่ใช่สินค้า แถวซ้ำ และรหัส `M`/`m` ที่ยังกำกวม ก่อนล็อกชุดข้อมูลทดลอง หากเปลี่ยนกฎให้แก้ config แล้วรันใหม่ทั้งชุด
4. เพื่อนรับไฟล์ train/validation/test ที่สร้างในเครื่องจาก pipeline และตรวจ data contract ใน [`data_dictionary.md`](data_dictionary.md); อย่าใช้ target หรืออนาคตเป็น feature
5. ทำ baseline ที่ตีความง่าย เช่น naive/ค่าเฉลี่ยย้อนหลัง แล้วกำหนด metric และเปรียบเทียบโมเดลด้วย validation/test ตามเวลา
6. เพิ่มข้อมูล stock-on-hand, lead time หรือ reorder policy หากต้องสาธิตคำแนะนำเติมสินค้า; หากหาไม่ได้ให้จำกัดผลสาธิตเป็น demand forecast
7. พัฒนาส่วน production ตาม rubric ที่ยืนยันแล้ว: model registry, API, monitoring, drift, retraining และ rollback

## วิธีทำงานร่วมกันบน GitHub

- ใช้ branch แยกตามงาน และเขียนชื่อ branch ให้สื่อหน้าที่ เช่น `data/eda` หรือ `model/baseline`
- อย่า commit workbook, CSV/Parquet ที่สร้าง, model binary, credentials หรือ `.env`
- เมื่อเปลี่ยน data contract หรือ target ให้แก้เอกสารนี้, `config/dataset.yaml` และ README ใน commit เดียวกัน
- เปิด Pull Request เพื่อให้สมาชิกอีกคนทบทวนก่อน merge
