# ระบบพยากรณ์ยอดขายสินค้า 7 วันล่วงหน้า

## Airflow Orchestration — งานคนที่ 6

ติดตั้ง Git และ Docker Desktop (Linux containers) แล้วจาก PowerShell ที่ root ของโปรเจกต์สั่ง:

```powershell
.\scripts\run_orchestration.ps1
```

คำสั่งนี้ build จาก dependency lock, เปิด Airflow/candidate/production ใน Docker volume แยก, รัน DAG จากข้อมูลดิบผ่านการเทรนและ gate, ลงทะเบียนและ export โมเดล, ทดสอบ candidate, อนุมัติตาม policy สำหรับ local demo, สลับบริการ, สาธิต rollback แล้วคืนรุ่นที่อนุมัติ และเก็บหลักฐาน Monitoring/retraining หน้าจอ Airflow คือ http://127.0.0.1:18090 และ API ของชุด orchestration คือ http://127.0.0.1:18015/docs ผลรันถูกคัดลอกออกมาที่ `reports/orchestration/` ไม่ต้องติดตั้ง Python บน host

อ่าน [คู่มือ Pipeline Orchestration](docs/pipeline_orchestration.md) สำหรับความหมายแต่ละ task, การเข้าสู่ Airflow, negative tests, delayed labels, การกู้คืน และข้อจำกัดการอนุมัติของเดโม การสาธิต drift ใช้ข้อมูลสังเคราะห์ที่ติดป้ายชัดเจนและไม่ถูกส่งขึ้นบริการจริง CI/CD ยังเป็นขั้นถัดไป

## Monitoring, Drift และ Retraining — งานคนที่ 5

มีตัวเก็บ prediction observations จาก `/predict`, ตรวจ data drift และคุณภาพเมื่อ label ครบ 7 วัน, แจ้ง suspected concept drift, ตรวจสถานะบริการ และสร้าง LightGBM candidate หลัง degradation สองช่วงติดกัน พร้อมชุดสาธิตออฟไลน์ อ่านคำสั่งและข้อจำกัดใน [คู่มือ Monitoring และ Retraining](docs/monitoring_retraining.md)

## FastAPI และ Docker — งานคนที่ 4

ชุด Model Serving อยู่ใน [`serving/`](serving/README_TH.md) มี `/predict`, `/health`, `/schema`, Prometheus `/metrics`, JSON logs และ load test เปิด Docker แล้วรันจาก root:

```bash
cd serving
docker compose up --build -d
```

เปิด http://localhost:18005/docs คำสั่ง Compose แบบเดิมข้างต้นใช้โมเดลสังเคราะห์สำหรับสาธิต ส่วน `compose.model.yaml` ใช้ bundle joblib ของโมเดลจริงที่เตรียมไว้ และชุด Airflow ด้านบนสร้างและสลับ bundle จาก run ได้เอง Registry benchmark ปัจจุบันเรียก `/predict` แบบ `records` และเทียบ prediction กับ Registry ดูรายละเอียดในคู่มือ serving และ orchestration

## MLflow และ Model Registry

หลังรัน Experiment 1–3 แล้ว ใช้คำสั่ง `python -m src.demand_forecasting.registry track`, `check`, `register`, `promote <version>` และ `rollback` เพื่อบันทึกการทดลอง ตรวจคุณภาพ ลงทะเบียน เลื่อนรุ่น และย้อนกลับ รายละเอียดและเกณฑ์อยู่ใน [คู่มือ MLflow](docs/mlflow_registry.md)

โปรเจกต์นี้พยากรณ์จำนวนหน่วยสินค้าที่ขายได้ของแต่ละ SKU ใน 7 วันถัดไปจากข้อมูลธุรกรรมย้อนหลัง ครอบคลุมการเตรียมข้อมูล การสร้าง features การฝึกโมเดล และการประเมินผลตามลำดับเวลา

## ข้อมูลและเป้าหมาย

ใช้ชุดข้อมูล [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii) จาก UCI Machine Learning Repository ([DOI: 10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)) ซึ่งมีรายการธุรกรรมระหว่างเดือนธันวาคม 2009 ถึงธันวาคม 2011

หนึ่งตัวอย่างแทน **1 SKU ณ วันตัดข้อมูล `t`** และ target `demand_next_7d_units` คือยอดขายรวมตั้งแต่ `t+1` ถึง `t+7` วันปฏิทิน ใช้เฉพาะข้อมูลที่ทราบได้ไม่เกินสิ้นวัน `t` ในการสร้าง features รายการยกเลิกที่ invoice ขึ้นต้นด้วย `C` และรายการที่ `Quantity <= 0` ไม่ถูกนับเป็นยอดขาย วันไม่มีรายการขายเติมเป็นศูนย์ และตัดตัวอย่างท้ายชุดข้อมูลที่มีช่วง target ไม่ครบ

Target เป็น **ยอดขายที่สังเกตได้** ชุดข้อมูลไม่มีข้อมูลสินค้าคงคลังหรือ stockout จึงไม่สามารถตีความผลเป็นความต้องการที่แท้จริงหรือจำนวนที่ควรสั่งซื้อได้ รายละเอียดอยู่ใน [นิยามโจทย์](docs/problem_definition.md) และ [data dictionary](docs/data_dictionary.md)

## ติดตั้งและเตรียมข้อมูล

ใช้ Python 3.12 จาก root ของ repository:

```bash
python -m venv .venv
```

เปิด virtual environment ด้วย `.venv\Scripts\Activate.ps1` บน Windows PowerShell หรือ `source .venv/bin/activate` บน macOS/Linux แล้วรัน:

```bash
python -m pip install -r requirements.txt
python scripts/run_data_pipeline.py
```

Pipeline ดาวน์โหลดข้อมูลต้นทางเมื่อยังไม่มีไฟล์ สร้างตารางยอดขายรายวัน ตรวจความถูกต้อง แบ่งข้อมูลตามเวลา และสร้าง lag, rolling และ calendar features ผลลัพธ์หลักอยู่ใน `data/processed/` ได้แก่ `train_features_7d.csv.gz`, `validation_features_7d.csv.gz` และ `test_features_7d.csv.gz` ขั้นตอนและกฎตรวจข้อมูลอธิบายใน [เอกสาร Data Pipeline](docs/data_pipeline_feature_engineering.md)

ข้อมูลดิบ ข้อมูลที่แปลงแล้ว และ model artifacts ถูก `.gitignore` และสร้างซ้ำได้จากสคริปต์ใน repository

## การทดลองโมเดล

ใช้ MAE เป็น metric สำหรับเลือกโมเดล และรายงาน RMSE กับ WAPE เพิ่มเติม Experiment 1 ใช้ validation ช่วงเดียว ส่วน Experiment 2–3 ใช้ expanding-window validation 4 folds โดยเว้น 7 วันระหว่างข้อมูลฝึกกับ validation เพื่อไม่ให้ช่วง label คาบเกี่ยวกัน การฝึกใน Experiment 2–3 ใช้ deterministic sample 150,000 แถวต่อ fold เพื่อควบคุมเวลาในการทดลอง

| การทดลอง | โมเดลอ้างอิงหรือโมเดลที่เลือก | Validation MAE | RMSE | WAPE |
|---|---|---:|---:|---:|
| Experiment 1: single validation | Historical 7-day sum | 19.2015 | 83.4931 | 87.41% |
| Experiment 2: 4 folds | LightGBM L1 | 16.4186 | 82.3937 | 72.31% |
| Experiment 3: 4 folds | LightGBM L1, `l1_more_trees` | **16.2275** | **81.1147** | **71.28%** |

ผล Experiment 1 เป็น validation ช่วงเดียว จึงไม่ควรเทียบค่า MAE ตรงกับค่าเฉลี่ย 4 folds ของ Experiment 2–3 บน folds เดียวกัน baseline มี mean MAE **20.8549** และ `l1_more_trees` ชนะ baseline **4/4 folds** หรือดีขึ้น **22.19%** ตาม mean MAE

### ตรวจสอบด้วยข้อมูลฝึกเต็มต่อ fold

หลังเลือก `l1_more_trees` แล้ว มีการฝึกโมเดลนี้ซ้ำโดยใช้ training rows ทั้งหมดของแต่ละ fold โดยคง validation, features, hyperparameters และ metrics เดิม

| Training rows ต่อ fold | Mean MAE ± std | Mean RMSE | Mean WAPE | ชนะ baseline |
|---|---:|---:|---:|---:|
| Sample 150,000 rows | 16.2275 ± 4.7564 | 81.1147 | 71.28% | 4/4 |
| Full rows (967,606–2,141,532) | **16.2581 ± 4.6680** | **81.7405** | **71.55%** | **4/4** |

Full-fold MAE สูงกว่าผลแบบ sample 0.0306 หน่วย และยังต่ำกว่า baseline 22.04% การตรวจนี้ใช้ validation folds เดิม จึงเป็นการตรวจความแข็งแรงของผลหลังเลือกโมเดล ไม่ใช่ holdout อิสระ รายละเอียดราย fold และการเปรียบเทียบทุก trial อยู่ใน [รายงานการทดลอง](docs/model_experiments.md)

## Final Candidate และการรันซ้ำ

Final Candidate คือ LightGBM `regression_l1` trial `l1_more_trees` (`n_estimators=240`, `learning_rate=0.05`, `num_leaves=31`, seed 42) หลังเลือกโมเดล ฝึก final artifact ด้วยข้อมูล train และ validation ก่อน test ทั้งหมด **2,536,231 แถว** โดยไม่ sample

หลังสร้างข้อมูลด้วย pipeline แล้ว รันการทดลองและ tests จาก root ของ repository:

```bash
python -m src.demand_forecasting.training.experiment2
python -m src.demand_forecasting.training.experiment3
python -m src.demand_forecasting.training.verify_full_folds
python -m unittest discover -s tests -v
```

คำสั่งเรียงตาม dependency ของ artifacts ที่สร้างขึ้น ผลการทดลองและโมเดลบันทึกใน `artifacts/training/` ซึ่งถูก ignore จาก Git การตั้งค่าอยู่ใน `config/training.json` และผล Experiment 1 ที่ใช้เป็น reference อยู่ใน `config/experiment1_reference.json`

## ข้อจำกัด

- ผล test aggregate ถูกตรวจดูใน Experiment 1 แล้ว จึงไม่มี untouched test set สำหรับอ้างผลประเมินอิสระของ Final Candidate ผลที่รายงานสำหรับโมเดลนี้มาจาก validation folds
- ยอดขายสูงบางช่วงยังถูกทำนายต่ำกว่าจริง แม้การปรับโมเดลจะลด error ของกลุ่มนี้เมื่อเทียบกับ LightGBM L1 reference
- ชุดข้อมูลไม่มีข้อมูล stockout, จำนวนสินค้าคงคลัง และ lead time สำหรับประเมินผลด้านการเติมสินค้า
