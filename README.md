# ระบบพยากรณ์ความต้องการสินค้าเพื่อวางแผนสินค้าคงคลัง

โครงงานรายวิชา CP413008: Machine Learning Engineering for Production

โครงงานนี้กำหนดโจทย์ ข้อมูล และ target สำหรับพยากรณ์ยอดขายสินค้าแต่ละ SKU ล่วงหน้า 7 วัน พร้อม Data Pipeline ที่สร้างข้อมูลสำหรับฝึกโมเดลซ้ำได้จากข้อมูลต้นทาง

## สถานะ

- ขั้นตอนที่ 1: เลือก dataset, นิยาม target, วางโครงสร้าง repository และเตรียมสคริปต์ข้อมูล — จัดทำแล้ว
- งาน Data Pipeline + Feature Engineering: clean ข้อมูล, aggregate รายวัน, ตรวจความถูกต้อง, แบ่งตามเวลา และสร้าง lag/rolling/calendar features — จัดทำแล้ว ดู [`docs/data_pipeline_feature_engineering.md`](docs/data_pipeline_feature_engineering.md)
- ข้อมูลจริง: ดาวน์โหลดและแปลงในเครื่องแล้ว; ดูผลการรับข้อมูลที่ [`docs/data_intake.md`](docs/data_intake.md) ไฟล์ข้อมูลดิบและผลแปลงไม่ถูก commit เพื่อให้สมาชิกสร้างซ้ำบนเครื่องตนเอง
- การตรวจทานกับเอกสารข้อกำหนดรายวิชา: ยังรอไฟล์ `โครงงานรายวิชา CP413008 Machine Learning Engineering for Production.docx` เนื่องจากไม่พบไฟล์ตาม path ที่ได้รับใน workspace นี้ ดูรายละเอียดที่ [`docs/course_requirements.md`](docs/course_requirements.md)
- โมเดล, API, monitoring, drift, retraining และ rollback — เป็นงานขั้นถัดไปของทีม

## Dataset ที่เลือก

**Online Retail II** จาก UCI Machine Learning Repository: รายการธุรกรรมของร้านค้าออนไลน์ในสหราชอาณาจักร ช่วง 1 ธันวาคม 2009 ถึง 9 ธันวาคม 2011 มีประมาณ 1.07 ล้านรายการ และมี SKU, ปริมาณสินค้า และเวลาทำรายการ เหมาะกับการสร้างอนุกรมเวลารายวันและการประเมินแบบแบ่งตามเวลา

- หน้า dataset และคำอธิบาย: [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
- ดาวน์โหลดไฟล์ต้นฉบับ: [UCI ZIP](https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip)
- ผู้จัดทำ: Daqing Chen. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository. [DOI: 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D)
- ใบอนุญาตข้อมูล: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); ให้อ้างอิงเจ้าของข้อมูลเมื่อนำไปใช้หรือเผยแพร่

ไฟล์ต้นฉบับและผลแปลงข้อมูลจะอยู่ใน `data/` บนเครื่องผู้ใช้และถูกละเว้นจาก Git เพื่อให้ repository มีขนาดเล็กและเพื่อนแต่ละคนสร้างข้อมูลซ้ำได้จากสคริปต์ ดู [`data/README.md`](data/README.md)

## นิยามโจทย์และ Target

ณ วันตัดข้อมูล `t` หลังปิดยอดของวันนั้น ระบบรับ SKU และประวัติที่มีถึงวัน `t` แล้วคาดการณ์จำนวนหน่วยที่ขายได้ใน **7 วันปฏิทินถัดไป `t+1` ถึง `t+7`**

```text
หน่วยข้อมูล: 1 SKU × 1 วันตัดข้อมูล
Target: demand_next_7d_units
ตัวอย่าง: ข้อมูลถึง 2025-01-01 → รวมยอดขาย 2025-01-02 ถึง 2025-01-08
```

Target เริ่มต้นคำนวณจากผลรวม `Quantity` ของรายการที่เป็นการขายจริง โดยตัด invoice ที่ขึ้นต้นด้วย `C` (ยกเลิก) และ `Quantity <= 0` (รายการคืน/ปรับลด) ออก วันไม่มีรายการขายเติมเป็นศูนย์ และไม่สร้างตัวอย่างที่ช่วง target 7 วันท้ายข้อมูลไม่ครบ

Target นี้เป็น **ยอดขายที่สังเกตได้** ไม่ใช่ความต้องการแฝงที่ถูกต้องครบถ้วน: dataset ไม่มีจำนวนคงเหลือ สถานะสินค้าหมด ระยะเวลาส่งสินค้า หรือการเติมสินค้า ทีมจึงยังสรุปจำนวนที่ควรสั่งหรือ stockout risk จาก dataset นี้เพียงอย่างเดียวไม่ได้ ควรนำข้อมูลคงคลังและ lead time มาเพิ่มก่อนทำคำแนะนำสั่งซื้อจริง

นิยามและข้อสมมติทั้งหมดอยู่ที่ [`docs/problem_definition.md`](docs/problem_definition.md) และ [`docs/data_dictionary.md`](docs/data_dictionary.md)

## เริ่มต้นใช้งาน

ใช้ Python 3.11 และติดตั้ง dependencies ที่ตรึงเวอร์ชันไว้

```bash
python -m venv .venv
```

เปิด virtual environment ก่อนติดตั้ง:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

จากนั้นใช้คำสั่งเดียวกันทุกระบบ:

```bash
python -m pip install -r requirements.txt
python scripts/run_data_pipeline.py
```

คำสั่งนี้ดาวน์โหลด/แตกไฟล์เมื่อยังไม่มี, เตรียมข้อมูล, ตรวจ Data Validation และสร้างไฟล์ `train_features_7d.csv.gz`, `validation_features_7d.csv.gz`, `test_features_7d.csv.gz` ใน `data/processed/` ไฟล์ข้อมูลดิบและผลแปลงไม่ถูก commit ขึ้น GitHub วิธีทำทีละขั้น กฎ clean นิยาม feature และช่วง split อยู่ใน [`docs/data_pipeline_feature_engineering.md`](docs/data_pipeline_feature_engineering.md)

## โครงสร้าง repository

```text
.
├── config/                 # ค่าตั้งต้นเกี่ยวกับ dataset, target, clean, features และ split
├── data/
│   ├── raw/                # ไฟล์จาก UCI (ไม่ commit)
│   ├── interim/            # ตารางยอดขายรายวันเต็มช่วง (ไม่ commit)
│   └── processed/          # target และไฟล์ train/validation/test (ไม่ commit)
├── docs/                   # นิยามโจทย์, data dictionary, ข้อกำหนด, handoff
├── notebooks/              # พื้นที่ notebook สำหรับวิเคราะห์เพิ่มเติม
├── reports/                # EDA และผลตรวจข้อมูล
├── scripts/                # ดาวน์โหลด เตรียม ตรวจ และสร้าง features
├── src/demand_forecasting/ # โค้ดระบบ ML ที่ทีมจะพัฒนาต่อ
├── models/                 # โมเดลที่สร้างในภายหลัง (ไม่ commit)
├── .gitignore
└── requirements.txt
```

## เผยแพร่ครั้งแรกด้วย GitHub Desktop

หากโฟลเดอร์นี้ยังไม่มี commit หรือ remote repository ให้เพิ่มเป็น local repository ใน GitHub Desktop โดยตรง ไม่ต้องสร้าง repository ซ้อนในโฟลเดอร์เดิม ผู้ที่ clone จาก GitHub แล้วให้ใช้คำสั่งสร้างข้อมูลในหัวข้อเริ่มต้นใช้งานแทน

1. ใน GitHub Desktop เลือก **File → Add local repository → Choose…** แล้วเลือกโฟลเดอร์ `cp413008-demand-forecasting` นี้
2. ตรวจรายการ **Changes** ว่ามี README, config, docs, scripts และไฟล์โครงสร้าง โดยไม่มี workbook หรือไฟล์ข้อมูลที่สร้างจาก dataset
3. บันทึก commit ที่อธิบายงานจริง เช่น `Set up CP413008 demand forecasting project` สำหรับโครงสร้างเริ่มต้น และ `Add data pipeline and feature engineering` สำหรับงานข้อมูล
4. กด **Publish repository** ตั้งชื่อ `cp413008-demand-forecasting` และเลือก **Keep this code private** หากกลุ่มยังไม่ได้ตกลงเผยแพร่สาธารณะ แล้วกด **Publish Repository**
5. เปิด repository บน GitHub ไปที่ **Settings → Collaborators → Add people** เพื่อเชิญเพื่อนในกลุ่ม จากนั้นส่ง URL ให้เพื่อน clone ด้วย GitHub Desktop

หลังจากนั้นให้แต่ละคนทำงานบน branch ของตนและส่ง Pull Request เพื่อทบทวนก่อนรวม

งานต่อที่แนะนำสำหรับกลุ่มสรุปไว้ใน [`docs/team_handoff.md`](docs/team_handoff.md)
