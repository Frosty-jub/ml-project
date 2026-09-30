# ข้อมูลสำหรับโครงงาน

ไม่เก็บไฟล์ข้อมูลจริงใน Git repository แต่ละคนดาวน์โหลดและสร้างข้อมูลแปลงเองจากโฟลเดอร์หลัก:

```bash
python scripts/run_data_pipeline.py
```

ถ้าดาวน์โหลด ZIP ผ่านเบราว์เซอร์แล้ว ให้วางไฟล์ไว้ที่ `data/raw/online_retail_II.zip` โดยใช้ชื่อนี้ จากนั้นรันคำสั่งข้างบน สคริปต์ดาวน์โหลดจะข้ามขั้นดาวน์โหลดและแตก workbook จาก ZIP ที่มีอยู่

## แหล่งที่มาและการอ้างอิง

- UCI Machine Learning Repository, [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), UCI dataset ID 502.
- Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository. [https://doi.org/10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D).
- UCI ระบุใบอนุญาตเป็น [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

## ไฟล์ที่สร้าง

| เส้นทาง | เนื้อหา |
|---|---|
| `data/raw/online_retail_II.zip` | ZIP ต้นฉบับที่ดาวน์โหลดจาก UCI |
| `data/raw/online_retail_II.xlsx` | workbook ต้นฉบับ มีข้อมูลแยกตาม sheet |
| `data/interim/sku_daily_sales.csv.gz` | ตารางยอดขายราย SKU ต่อวันเต็มช่วง ใช้ตรวจ target |
| `data/processed/sku_daily_demand_7d.csv.gz` | ตาราง SKU ต่อวัน พร้อมยอดขายวันนั้นและ target 7 วันถัดไป |
| `data/processed/train_features_7d.csv.gz` | features และ target ชุด train |
| `data/processed/validation_features_7d.csv.gz` | features และ target ชุด validation |
| `data/processed/test_features_7d.csv.gz` | features และ target ชุด test |

ไฟล์ใน `data/raw/`, `data/interim/` และ `data/processed/` ถูกละเว้นจาก Git โดยตั้งใจ หากจะเผยแพร่ชุดข้อมูลที่แปลงแล้ว ให้คงที่มาและ attribution ของ UCI ไว้ด้วย

ผลการรับและแปลงไฟล์ชุดแรกที่ทำจริงอยู่ใน [`docs/data_intake.md`](../docs/data_intake.md)

## กติกาเตรียมข้อมูลเริ่มต้น

สคริปต์อ่านทั้งสอง sheet, รวมข้อมูล, ตัด invoice ที่ขึ้นต้นด้วย `C`, ตัดรายการที่ `Quantity <= 0` และรหัสที่ไม่ใช่สินค้าตาม `config/pipeline.json`, รวมหน่วยขายราย `StockCode` และวัน แล้วเติมวันที่ไม่พบยอดขายเป็นศูนย์ต่อ SKU ตั้งแต่วันที่ขายครั้งแรกจนถึงวันสุดท้ายของข้อมูล

ตาราง target มีตัวอย่างถึงวันที่ `วันสุดท้ายที่พบ - 7 วัน` เพื่อให้ทุกแถวมีช่วง target ครบเจ็ดวัน กฎทั้งหมด ผล Data Validation และช่วงแบ่งชุดข้อมูลอธิบายใน [`docs/data_pipeline_feature_engineering.md`](../docs/data_pipeline_feature_engineering.md)
