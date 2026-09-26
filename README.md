# ระบบพยากรณ์ความต้องการสินค้าเพื่อวางแผนสินค้าคงคลัง

โครงงานรายวิชา CP413008: Machine Learning Engineering for Production

โครงงานนี้กำหนดโจทย์ ข้อมูล และ target สำหรับพยากรณ์ยอดขายสินค้าแต่ละ SKU ล่วงหน้า 7 วัน พร้อม Data Pipeline ที่สร้างข้อมูลสำหรับฝึกโมเดลซ้ำได้จากข้อมูลต้นทาง

## สถานะ

- ขั้นตอนที่ 1: เลือก dataset, นิยาม target, วางโครงสร้าง repository และเตรียมสคริปต์ข้อมูล — จัดทำแล้ว
- งาน Data Pipeline + Feature Engineering: clean ข้อมูล, aggregate รายวัน, ตรวจความถูกต้อง, แบ่งตามเวลา และสร้าง lag/rolling/calendar features — จัดทำแล้ว ดู [`docs/data_pipeline_feature_engineering.md`](docs/data_pipeline_feature_engineering.md)
- ข้อมูลจริง: ดาวน์โหลดและแปลงในเครื่องแล้ว; ดูผลการรับข้อมูลที่ [`docs/data_intake.md`](docs/data_intake.md) ไฟล์ข้อมูลดิบและผลแปลงไม่ถูก commit เพื่อให้สมาชิกสร้างซ้ำบนเครื่องตนเอง
- สรุปงาน Sira สำหรับอธิบายอาจารย์อยู่ที่ [`docs/Sira_Experiment_1-3_summary.md`](docs/Sira_Experiment_1-3_summary.md); ก่อนส่งงานให้เทียบผลงานกับ rubric ต้นฉบับที่อาจารย์แจก
- API, monitoring, drift, retraining และ rollback — เป็นงานขั้นถัดไปของทีม
- Baseline, model training และ evaluation — จัดทำบน branch `Sira` ตามรายละเอียดด้านล่าง

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

ใช้ Python 3.12 (เวอร์ชันที่ใช้ตรวจงาน Sira) และติดตั้ง dependencies ที่ตรึงเวอร์ชันไว้

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

หัวข้อนี้ใช้เฉพาะกรณีสร้าง repository ใหม่ หาก clone จาก GitHub แล้วให้ข้ามไปหัวข้อเริ่มต้นใช้งานได้เลย

1. ใน GitHub Desktop เลือก **File → Add local repository → Choose…** แล้วเลือกโฟลเดอร์ root ของ repository ที่สร้างไว้ (ชื่อโฟลเดอร์อาจต่างกันในแต่ละเครื่อง)
2. ตรวจรายการ **Changes** ว่ามี README, config, docs, scripts และไฟล์โครงสร้าง โดยไม่มี workbook หรือไฟล์ข้อมูลที่สร้างจาก dataset
3. บันทึก commit ที่อธิบายงานจริง เช่น `Set up CP413008 demand forecasting project` สำหรับโครงสร้างเริ่มต้น และ `Add data pipeline and feature engineering` สำหรับงานข้อมูล
4. กด **Publish repository** ตั้งชื่อ repository ตามที่ทีมตกลง และเลือก **Keep this code private** หากกลุ่มยังไม่ได้ตกลงเผยแพร่สาธารณะ แล้วกด **Publish Repository**
5. เปิด repository บน GitHub ไปที่ **Settings → Collaborators → Add people** เพื่อเชิญเพื่อนในกลุ่ม จากนั้นส่ง URL ให้เพื่อน clone ด้วย GitHub Desktop

หลังจากนั้นให้แต่ละคนทำงานบน branch ของตนและส่ง Pull Request เพื่อทบทวนก่อนรวม

งานต่อที่แนะนำสำหรับกลุ่มสรุปไว้ใน [`docs/team_handoff.md`](docs/team_handoff.md)

# Sira — Baseline, Model Training & Evaluation

## หน้าที่ของส่วนนี้

Sira รับไฟล์ train/validation/test และ feature manifest จาก Data Pipeline ของ Chawa แล้วทำ baseline → training experiments → evaluation เพื่อส่ง candidate และหลักฐานให้คนที่ 3 ทำ MLflow Tracking, Model Registry และ Quality Gate ต่อ ส่วนนี้ไม่สร้าง preprocessing ซ้ำและไม่ implement MLflow/Registry

โจทย์คือทำนายยอดขายที่สังเกตได้ของ 1 SKU ใน 7 วันถัดจาก forecast origin `t` โดยใช้ข้อมูลที่รู้ได้ถึงสิ้นวัน `t` เท่านั้น target คือ `demand_next_7d_units`; ข้อมูลไม่มี stock-on-hand จึงยังใช้คำว่า latent demand หรือจำนวนที่ควรสั่งซื้อจริงไม่ได้

## Experiment 1 — เราเริ่มจากอะไร

เริ่มด้วย baseline ผลรวมยอดขาย 7 วันย้อนหลัง (`sales_rolling_sum_7`) แล้วเปรียบเทียบ Ridge, Random Forest และ HistGradientBoosting บน validation เดียว (2011-07-01 ถึง 2011-09-23) ใช้ MAE เป็น optimizing metric และดู RMSE/WAPE เพิ่มเติม ผลที่ตรึงไว้ใน `config/experiment1_reference.json` คือ:

| Model | MAE | RMSE | WAPE (%) |
|---|---:|---:|---:|
| Historical 7-day sum | **19.2015** | 83.4931 | **87.41** |
| Ridge | 19.5602 | 68.3132 | 89.04 |
| Random Forest | 19.2387 | **66.2299** | 87.58 |
| HistGradientBoosting | 21.6345 | 85.2754 | 98.48 |

RF ลด RMSE จาก baseline ได้ แต่ยังแพ้ MAE เล็กน้อย เพราะทำนายเกินใน low/zero-demand หลายแถว จึงไม่ได้เปลี่ยน metric เพื่อให้ ML ชนะ และเริ่มวิเคราะห์ข้อมูลกับ error ก่อนทำรอบ 2

## Experiment 2 — ทำไมต้องเปลี่ยนแนวทาง

ใน train target เป็นศูนย์ 55.71%, ไม่เกิน 1 หน่วย 61.23%, ไม่เกิน 5 หน่วย 69.83% ผล validation ช่วงเดียวอาจขึ้นกับฤดูกาล จึงใช้ expanding-window validation 4 folds และช่องว่าง 7 วันระหว่าง train label กับ validation ทุก trial ใช้วันแบ่งชุดเดียวกัน ไม่มี shuffle และไม่เปิด test

ทดลอง RF แบบจำกัดชุด, LightGBM L1 และ two-stage (Logistic Regression ทำนายว่ามียอดขายหรือไม่ จากนั้น LightGBM บนแถว positive ทำนายปริมาณ) LightGBM L1 ได้ mean MAE **16.4186 ± 4.6943**, RMSE 82.3937, WAPE 72.31%; baseline บน folds เดียวกันได้ mean MAE **20.8549 ± 6.0846** จึงดีขึ้น **21.27%** และชนะ baseline 4/4 folds Two-stage ใกล้เคียงแต่ MAE ยังสูงกว่า ดูผลราย fold ทุก trial ที่ `artifacts/training/experiment2_fold_metrics.csv`

## Experiment 3 — ทำไมต้องทำต่อ

รอบนี้ตรวจความแข็งแรงของ LightGBM L1 ที่ชนะรอบ 2 โดยคง **features, target, 4 folds, metric implementation และ clipping เดิมทั้งหมด** Error analysis ใช้ข้อมูล validation เท่านั้น โดยกำหนด high demand เป็น `target > 111` จาก percentile 95 ของ target ใน train เดิม กลุ่มอื่นคือ zero, low 1–5 และ medium 6–111

Reference รอบ 2 ทำนายเกินใน zero demand (bias เป็นบวก) แต่พลาดหนักกว่าใน high demand: กลุ่ม high มี bias ทำนายต่ำกว่าจริงราว 168–220 หน่วยตาม fold; fold 1 ยากที่สุด ตัวอย่าง error สูงใน fold 4 คือ SKU `84568` ที่ origin 2011-07-27: actual 4,660, prediction ประมาณ 78 รายงานจำนวนแถว, MAE/RMSE, mean actual/prediction, bias และ SKU/error ตัวอย่างครบที่ `artifacts/training/experiment3_error_analysis.json`

จึงกำหนด trials ล่วงหน้าอย่างจำกัด: L1 เพิ่มจำนวนต้นไม้, L1 เพิ่มความจุ, L1 regularized และ Poisson สำหรับทดสอบ objective ของข้อมูลนับ ใช้ train sample 150,000 แถวต่อ fold และ seed 42 เหมือน reference เพื่อเทียบกันตรง ๆ ไม่มี early stopping เพราะ outer validation เดียวกันถูกใช้วัดและเลือกโมเดล; หากใช้มันหยุดต้นไม้ด้วยจะเพิ่มการใช้ validation ซ้ำโดยไม่มี inner window อิสระ Target เป็นจำนวนเต็มไม่ติดลบ แต่ variance/mean ประมาณ 813 จึง overdispersed มากและ Poisson เป็นเพียง stress test ไม่ใช่สมมติฐานที่เชื่อว่าตรงข้อมูล ส่วน Tweedie รองรับมวลที่ศูนย์และ positive ต่อเนื่อง แต่ target นี้เป็นหน่วยสินค้าจำนวนเต็ม จึงไม่เพิ่ม objective อีกตัว Two-stage ไม่ได้ปรับเพิ่มเพราะ zero-error เฉลี่ยต่ำกว่า high-error มากและรอบ 2 ไม่ชนะ L1 ตาม MAE

| Experiment 3 trial | Mean MAE ± std | Mean RMSE | Mean WAPE (%) | ดีขึ้นจาก Exp2 L1 | ดีขึ้นจาก baseline | ชนะ baseline |
|---|---:|---:|---:|---:|---:|---:|
| **L1 more trees** | **16.2275 ± 4.7564** | 81.1147 | **71.28** | **+1.16%** | **+22.19%** | **4/4** |
| L1 capacity | 16.2597 ± 4.7017 | **80.6663** | 71.53 | +0.97% | +22.03% | 4/4 |
| Exp2 LightGBM L1 reference | 16.4186 ± 4.6943 | 82.3937 | 72.31 | 0% | +21.27% | 4/4 |
| L1 regularized | 16.4441 ± 4.7510 | 82.8977 | 72.34 | −0.16% | +21.15% | 4/4 |
| Historical 7-day sum | 20.8549 ± 6.0846 | 103.4738 | 91.52 | −27.02% | 0% | — |
| Poisson count | 21.5990 ± 7.5018 | 82.1352 | 93.80 | −31.55% | −3.57% | 2/4 |

Poisson ช่วย high-demand MAE บางส่วน แต่ overpredict zero มากกว่าและ mean MAE แพ้ baseline รอบนี้จึงไม่เลือก ผลราย fold และทุก segment อยู่ที่ `experiment3_fold_metrics.csv` และ `experiment3_segment_metrics.csv` ใน `artifacts/training/`

## Final Candidate

เลือก **LightGBM `regression_l1`, trial `l1_more_trees`** ด้วย mean validation MAE ต่ำสุดบน folds เดิม: **16.2275 ± 4.7564**, RMSE **81.1147**, WAPE **71.28%**, ดีขึ้นจาก baseline **22.19%**, ชนะ baseline **4/4 folds** ค่าสำคัญคือ `n_estimators=240`, `learning_rate=0.05`, `num_leaves=31`, `min_child_samples=50`, `subsample=0.8`, `colsample_bytree=0.8`, `reg_alpha=0.1`, `reg_lambda=1.0`, seed 42

หลังเลือกแล้วฝึก `final_candidate_model.joblib` ใหม่ด้วย **ข้อมูลก่อน test ทั้งหมด 2,536,231 แถว** จาก train + validation เดิม โดยไม่ sample ใน final fit โมเดลที่ save มี feature order และ production prediction ตัดค่าติดลบเป็นศูนย์ ค่า validation ด้านบนเป็นของ fold models ที่ฝึก 150,000 แถวต่อ fold **ไม่ได้เป็นการวัด artifact ที่ refit แล้วบน untouched test**

### ตรวจความแข็งแรงด้วย training rows เต็มในแต่ละ fold

การเลือก Final Candidate ข้างต้นใช้ deterministic sample 150,000 training rows ต่อ fold เพื่อจำกัดเวลาและทรัพยากร หลังเลือกโมเดลแล้ว จึงตรวจเฉพาะ `l1_more_trees` บน **4 validation folds เดิม** โดยฝึกใหม่ด้วย training rows ทุกแถวของแต่ละ fold; ไม่ปรับ hyperparameters และไม่เปิด test

| Fold | Training rows | MAE แบบ sample | MAE แบบเต็ม | RMSE แบบเต็ม | WAPE แบบเต็ม | Baseline MAE |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 967,606 | 24.3461 | 24.2086 | 127.2610 | 69.07% | 31.2150 |
| 2 | 1,350,367 | 13.5197 | 13.8056 | 69.2131 | 80.14% | 16.2549 |
| 3 | 1,739,235 | 12.3795 | 12.3213 | 63.5116 | 70.09% | 16.7483 |
| 4 | 2,141,532 | 14.6647 | 14.6970 | 66.9763 | 66.90% | 19.2015 |
| **เฉลี่ย** | — | **16.2275** | **16.2581** | **81.7405** | **71.55%** | **20.8549** |

Full-fold mean MAE **16.2581 ± 4.6680**, สูงกว่า sampled-fold **0.0306** หน่วย แต่ยังต่ำกว่า baseline **22.04%** และชนะ **4/4 folds** นี่คือ robustness verification หลังเลือกโมเดลบน validation ชุดเดิม ไม่ใช่ holdout อิสระหรือการเลือกโมเดลรอบใหม่ ผลเต็มอยู่ที่ `artifacts/training/final_candidate_full_fold_summary.json` และ `artifacts/training/final_candidate_full_fold_metrics.csv` (ไฟล์ที่สร้างซ้ำได้และถูก ignore) อ่านคำอธิบายรวมใน [`docs/Sira_Experiment_1-3_summary.md`](docs/Sira_Experiment_1-3_summary.md)

## เหตุผลที่เลือก

L1 more trees ลด mean MAE จาก Exp2 L1 อีก **1.16%** และชนะ reference รอบ 2 ทั้ง 4 folds แต่ความต่างยังเล็ก: MAE std เพิ่มจาก 4.6943 เป็น 4.7564 กลุ่ม high demand ดีขึ้น (mean segment MAE 196.83 → 191.14) ขณะที่ zero และ low แย่ลงเล็กน้อย (zero 1.07 → 1.16, low 4.81 → 4.97) จึงเลือกตาม metric ที่ล็อกไว้และบันทึก tradeoff นี้ให้คนที่ 3 ใช้พิจารณา gate ด้วย

## สิ่งที่เราไม่ได้ทำ

Experiment 2 และ 3 ไม่ใช้ test เพื่อเลือก model, features, threshold หรือ objective แต่ผล test aggregate เคยถูกเปิดดูใน Experiment 1 แล้ว และ dataset ไม่มีช่วงใหม่สำหรับ pristine holdout จึง **ไม่อ้าง unbiased final test performance** ของ Final Candidate หลักฐานที่ใช้คือ time-based validation 4 folds ยังไม่มี MLflow, Registry หรือ Quality Gate ที่ implement ในส่วน Sira

## ส่งต่อให้คนที่ 3

ให้คนที่ 3 log `final_candidate_model.joblib`, params, fold metrics และ aggregate metrics, ผลตรวจ full folds จาก `final_candidate_full_fold_summary.json`, baseline, segment/error analysis, feature list/order, target/horizon, seed, split dates, data/code checksums, Git commit/dirty state, dependency versions และข้อจำกัดของ test จาก `final_candidate_metadata.json` ลง MLflow Tracking จากนั้นทำ Model Registry และ Quality Gate ตามความรับผิดชอบของคนที่ 3 ไฟล์ summary รวม 3 รอบคือ `experiment1_2_3_summary.csv`/`.json`

## Recommended Quality Gates

**ยังไม่ได้ implement ในส่วน Sira** เสนอให้คนที่ 3 ใช้หลักฐานเหล่านี้กำหนด policy:

- Performance: Final Candidate mean validation MAE ต่ำกว่า baseline บน folds เดียวกัน
- Robustness: ชนะ baseline อย่างน้อย 3/4 folds เป็น **recommended project policy** ที่ต้องตกลงก่อนใช้จริง
- Model integrity: load artifact, predict ได้, ผล finite และไม่ติดลบ
- Feature compatibility: feature names/order ของ request ตรงกับ `feature_list.json` และ training metadata

## วิธีรัน

ใช้ Python 3.12 และติดตั้ง `requirements.txt` จาก repository root:

```bash
python -m pip install -r requirements.txt
python scripts/run_data_pipeline.py
python -m src.demand_forecasting.training.experiment2
python -m src.demand_forecasting.training.experiment3
python -m src.demand_forecasting.training.verify_full_folds
python -m unittest discover -s tests -v
```

ถ้าข้อมูลที่ Chawa สร้างมีแล้ว ข้าม Data Pipeline ได้ คำสั่ง Experiment 2 สร้าง reference artifacts ที่ Experiment 3 ตรวจเทียบก่อนรัน คำสั่งตรวจ full folds ใช้ artifacts จากสองรอบนั้นเพื่อยืนยัน protocol ทั้งสามคำสั่งใช้เฉพาะ train + validation; ไม่โหลด test ผล Experiment 1 ที่ตรึงไว้ใน `config/experiment1_reference.json` ใช้สร้าง summary โดยไม่ต้องเปิด test อีก หากต้องสร้าง Experiment 1 artifacts เดิมใหม่จริง ๆ ใช้ `python -m src.demand_forecasting.training.train` ซึ่งยังประเมิน test เดิมอยู่; ห้ามนำผลนั้นมาปรับรอบ 2/3

Artifacts ใน `artifacts/training/` และ dataset ใน `data/` ถูก `.gitignore` จึงต้องรันคำสั่งข้างบนเพื่อ regenerate บนเครื่องของคนที่ 3 ก่อนนำไป log ใน MLflow

## ไฟล์สำคัญ

| Path | หน้าที่ |
|---|---|
| `config/training.json` | seed, folds, จำนวนแถว และ trial parameters ทั้ง 3 รอบ |
| `config/experiment1_reference.json` | ผล Experiment 1 ที่ตรึงไว้ พร้อม source/pipeline checksums |
| `src/demand_forecasting/training/train.py` | Experiment 1 |
| `src/demand_forecasting/training/experiment2.py` | Experiment 2 และ reference artifacts |
| `src/demand_forecasting/training/experiment3.py` | error analysis, trials, comparison และ final fit |
| `src/demand_forecasting/training/verify_full_folds.py` | ตรวจ Final Candidate บน training rows เต็มใน 4 folds เดิม |
| `src/demand_forecasting/training/models.py` | model wrapper สำหรับ save/load และ feature order |
| `src/demand_forecasting/training/metrics.py` | MAE, RMSE, WAPE ใช้ร่วมกัน |
| `artifacts/training/final_candidate_model.joblib` | Final Candidate ที่ฝึกใหม่จาก pre-test rows ทั้งหมด |
| `artifacts/training/final_candidate_metadata.json` | หลักฐาน handoff สำหรับ MLflow/Registry |
| `artifacts/training/experiment3_error_analysis.json` | error/segment/SKU analysis ของ Exp2 reference |
| `artifacts/training/experiment1_2_3_summary.csv` | เรื่องราวและผลรวม 3 experiments |
| `artifacts/training/final_candidate_full_fold_summary.json` | ผล full-fold robustness verification ที่สร้างซ้ำได้และถูก ignore |
| `docs/Sira_Experiment_1-3_summary.md` | สรุปการทดลอง 3 รอบและผลตรวจ full folds สำหรับทีม/อาจารย์ |
