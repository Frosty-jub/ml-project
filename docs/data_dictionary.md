# Data dictionary

## คอลัมน์จากต้นทาง UCI

ชื่อใน workbook อาจแสดงเป็น `Invoice`, `Price`, `Customer ID` ขณะที่หน้า UCI แสดงชื่อมาตรฐานเช่น `InvoiceNo`, `UnitPrice`, `CustomerID` สคริปต์แปลงเฉพาะชื่อที่จำเป็นต่อโจทย์และรองรับชื่อเหล่านี้ทั้งสองแบบ

| คอลัมน์มาตรฐาน | ชนิด | ความหมาย / การใช้ |
|---|---|---|
| `invoice_id` | string | หมายเลข invoice; ใช้ตรวจ prefix `C` สำหรับการยกเลิก |
| `sku_id` | string | รหัสสินค้า; ใช้เป็น key ของอนุกรมเวลา |
| `quantity` | integer | จำนวนหน่วยในบรรทัดธุรกรรม; ใช้หลังกรองค่าที่ไม่เป็นบวก |
| `invoice_datetime` | datetime | วันและเวลาที่สร้างธุรกรรม; ยุบเวลาเป็นวันปฏิทิน |
| `unit_price` | number | ราคาต่อหน่วย; ยังไม่ใช้คำนวณ target |

คอลัมน์ชื่อสินค้า ลูกค้า และประเทศมีอยู่ในชุดข้อมูลต้นทาง แต่อาจมีค่าว่าง และยังไม่เป็น feature ของ baseline ที่กำหนดไว้

## ตารางที่เตรียมแล้ว

ไฟล์ `data/processed/sku_daily_demand_7d.csv.gz` มีคอลัมน์ดังนี้:

| คอลัมน์ | ชนิด | ความหมาย |
|---|---|---|
| `sku_id` | string | รหัสสินค้า |
| `forecast_origin_date` | date | วันสุดท้ายที่ใช้เป็นข้อมูล input |
| `daily_sold_units` | integer | ยอดขายบวกของ SKU ในวัน origin |
| `demand_next_7d_units` | integer | target: ยอดขายบวกสะสมใน 7 วันหลัง origin |

ไฟล์นี้เป็น panel รายวันตั้งแต่วันขายครั้งแรกที่สังเกตได้ของแต่ละ SKU ถึงวัน origin สุดท้ายที่ยังมี label ครบเจ็ดวัน วันระหว่างนั้นที่ไม่มียอดขายจะมีค่า `daily_sold_units = 0`

## ตารางรายวันเต็มช่วงและไฟล์สำหรับโมเดล

`data/interim/sku_daily_sales.csv.gz` มี `sku_id`, `date`, `daily_sold_units` จนถึงวันสุดท้ายของข้อมูล เพื่อให้ `scripts/validate_data.py` คำนวณ target 7 วันซ้ำได้ทุกแถว

ไฟล์ `data/processed/train_features_7d.csv.gz`, `validation_features_7d.csv.gz`, `test_features_7d.csv.gz` มี 4 คอลัมน์จากตาราง target ด้านบน และเพิ่ม:

| คอลัมน์ | ชนิด | ความหมาย |
|---|---|---|
| `days_since_first_sale` | integer | จำนวนวันนับจากวันขายครั้งแรกที่พบของ SKU |
| `sales_lag_1`, `_7`, `_14`, `_28` | integer | จำนวนขายเมื่อ 1, 7, 14, 28 วันก่อน origin |
| `sales_rolling_sum_7`, `_14`, `_28` | integer | ผลรวมยอดขายย้อนหลังตามจำนวนวัน โดยรวมวัน origin |
| `day_of_week` | integer 0–6 | จันทร์=0, อาทิตย์=6 |
| `month` | integer 1–12 | เดือนของวัน origin |
| `is_weekend` | integer 0/1 | วัน origin เป็นเสาร์หรืออาทิตย์หรือไม่ |

`demand_next_7d_units` เป็น label ไม่ใช่ feature; `sku_id` เป็นรหัสสำหรับระบุสินค้าและอาจใช้เป็น categorical feature เมื่อจัดการ SKU ใหม่ที่ไม่เคยพบใน train ได้ รายละเอียดการ clean, validation และ time split อยู่ใน [`data_pipeline_feature_engineering.md`](data_pipeline_feature_engineering.md)
