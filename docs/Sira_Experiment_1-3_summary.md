# สรุปงาน Sira: Baseline, Model Training & Evaluation

เอกสารนี้ใช้ผลจริงจาก branch `Sira` และ artifacts ของ Experiment 1–3 ณ วันที่ 26 กันยายน 2026 สำหรับอธิบายงานส่วน Sira ให้อาจารย์และส่งต่อเพื่อนในทีม

## 1. Problem

ระบบทำนาย **ยอดขายที่สังเกตได้ของแต่ละ SKU รวม 7 วันข้างหน้า** โดยใช้ข้อมูลที่รู้ถึงสิ้นวันปัจจุบัน ผลทำนายอาจช่วยฝ่าย inventory เตรียมแผนสินค้าล่วงหน้า แต่ dataset ไม่มีจำนวนสินค้าคงคลัง ระยะเวลาจัดส่ง หรือข้อมูล stockout จึงยังคำนวณจำนวนที่ควรสั่งซื้อหรือวัดผลกระทบด้าน inventory จริงไม่ได้

## 2. Baseline

ใช้ยอดขายรวม 7 วันย้อนหลังคาดการณ์ยอดขายรวม 7 วันถัดไป (`sales_rolling_sum_7`) Baseline นี้ง่าย อธิบายได้ และแข็งแรง: Experiment 1 ได้ validation MAE **19.2015** ชนะ Ridge, Random Forest และ HistGradientBoosting ตาม metric หลัก การมี baseline ป้องกันการเลือก ML เพียงเพราะดูซับซ้อน

## 3. Optimizing Metric

ล็อก **MAE** เป็น metric หลักตั้งแต่ต้น เพราะตีความเป็นจำนวนหน่วยที่พยากรณ์คลาดเคลื่อนเฉลี่ยต่อ SKU-origin ได้ตรง ๆ ใช้ **RMSE** ดูความเสี่ยงจาก error ขนาดใหญ่ และ **WAPE (%)** ดู error เทียบปริมาณยอดขายจริงโดยรวม WAPE อาจนิยามไม่ได้เมื่อยอดจริงรวมเป็นศูนย์และทำนายผิด จึงไม่ใช้แทน MAE เพื่อเลือกโมเดล

## 4. Experiment 1

**สมมติฐาน:** โมเดล ML อาจเรียนรู้ lag/rolling/calendar patterns แล้วชนะ baseline ได้ ทดลอง Ridge, Random Forest และ HistGradientBoosting เทียบยอดขาย 7 วันย้อนหลังบน validation ช่วง 2011-07-01 ถึง 2011-09-23

| Model | MAE | RMSE | WAPE |
|---|---:|---:|---:|
| Baseline | **19.2015** | 83.4931 | **87.41%** |
| Ridge | 19.5602 | 68.3132 | 89.04% |
| Random Forest | 19.2387 | **66.2299** | 87.58% |
| HistGradientBoosting | 21.6345 | 85.2754 | 98.48% |

**บทเรียน:** RF ลด large errors จึงทำ RMSE ดีขึ้น แต่ overpredict แถวที่ demand ต่ำหรือเป็นศูนย์จน MAE แพ้ baseline เล็กน้อย นี่เป็นเหตุผลให้วิเคราะห์ distribution/error แล้วออกแบบ Experiment 2

## 5. Experiment 2

Train target เป็นศูนย์ **55.71%**, ไม่เกิน 1 หน่วย **61.23%**, ไม่เกิน 5 หน่วย **69.83%** และ validation ช่วงเดียวอาจไม่สะท้อนทุกฤดูกาล จึงเปลี่ยนเป็น **4 expanding-window folds** ที่มี gap 7 วันและใช้ folds เดียวกันทุก trial ทดลอง RF แบบจำกัดขอบเขต, LightGBM L1 และ two-stage แยก zero/positive

LightGBM L1 ได้ mean MAE **16.4186 ± 4.6943**, RMSE **82.3937**, WAPE **72.31%** ขณะที่ baseline บน folds เดียวกันได้ MAE **20.8549 ± 6.0846** จึงดีขึ้น **21.27%** และชนะ baseline **4/4 folds** Two-stage ใกล้แต่ MAE ยังสูงกว่า จึงเลือก LightGBM L1 เป็น reference ของ Experiment 3

## 6. Experiment 3

**สมมติฐาน:** ปรับ LightGBM L1 อย่างจำกัดอาจลด error กลุ่มยอดขายสูงโดยยังรักษา MAE รวม ใช้ 4 folds, features, target และ metric เดิมทั้งหมด วิเคราะห์ error ของ reference ก่อน: กลุ่ม high (`target > 111`, percentile 95 ของ train) ถูกทำนายต่ำกว่าจริงเฉลี่ยประมาณ **168–220 หน่วย** ตาม fold ส่วนกลุ่ม zero ถูกทำนายเกิน แต่ error เฉลี่ยต่ำกว่ากลุ่ม high มาก Fold 1 ยากที่สุด

ทดลอง L1 เพิ่มจำนวนต้นไม้, L1 เพิ่มความจุ, L1 regularized และ Poisson เป็น objective เปรียบเทียบสำหรับข้อมูลนับ Target เป็นจำนวนเต็มไม่ติดลบแต่ variance/mean ประมาณ **813** จึง overdispersed มาก; Poisson เป็น stress test ไม่ใช่สมมติฐานที่ตรงข้อมูลมากที่สุด ไม่เพิ่ม Tweedie เพราะ positive target เป็นจำนวนหน่วยสินค้าจำนวนเต็ม และไม่ทำ two-stage เพิ่มเพราะรอบ 2 ยังไม่ชนะ L1 ตาม MAE

| Trial | Mean MAE ± std | RMSE | WAPE | ดีขึ้นจาก baseline | ชนะ baseline |
|---|---:|---:|---:|---:|---:|
| **L1 more trees** | **16.2275 ± 4.7564** | 81.1147 | **71.28%** | **22.19%** | **4/4** |
| L1 capacity | 16.2597 ± 4.7017 | **80.6663** | 71.53% | 22.03% | 4/4 |
| Exp2 LightGBM L1 | 16.4186 ± 4.6943 | 82.3937 | 72.31% | 21.27% | 4/4 |
| L1 regularized | 16.4441 ± 4.7510 | 82.8977 | 72.34% | 21.15% | 4/4 |
| Baseline | 20.8549 ± 6.0846 | 103.4738 | 91.52% | 0% | — |
| Poisson | 21.5990 ± 7.5018 | 82.1352 | 93.80% | −3.57% | 2/4 |

**บทเรียน:** L1 more trees ชนะ reference รอบ 2 อีก **1.16%** ตาม mean MAE และชนะ reference ทั้ง 4 folds แต่ความต่างไม่มาก ค่า MAE std เพิ่มจาก 4.6943 เป็น 4.7564 High-demand MAE เฉลี่ยดีขึ้น **196.83 → 191.14** ขณะที่ zero/low MAE แย่ลงเล็กน้อย จึงต้องส่ง tradeoff นี้ให้คนที่ 3 ด้วย

## 7. เปรียบเทียบ 3 Experiments

| Experiment | Problem/Hypothesis | Change | Best Result | Lesson | Decision |
|---|---|---|---|---|---|
| 1 | ML จะชนะ baseline หรือไม่ | ลอง 3 families กับ single validation | Baseline MAE 19.2015 | RF ลด RMSE แต่แพ้ MAE และ overpredict low demand | วิเคราะห์ error เพิ่ม |
| 2 | Zero-heavy + ช่วงเวลาเดียวไม่พอ | 4 folds; RF/LightGBM/two-stage | LightGBM L1 MAE 16.4186, ดีขึ้น 21.27% | ชนะ baseline 4/4 folds | ใช้ L1 เป็น reference |
| 3 | ปรับ L1 ให้ดีและเสถียรขึ้น | Tuning จำกัด, Poisson stress test, segment analysis | L1 more trees MAE 16.2275, ดีขึ้น 22.19% | ดีขึ้นอีก 1.16% แต่ zero/low แย่ลงเล็กน้อย | Final Candidate |

ผล MAE ของ Experiment 1 เป็น single period; Experiment 2/3 เป็นค่าเฉลี่ย 4 folds จึง **ไม่เทียบตัวเลขสองวิธีตรง ๆ**

## 8. Model Selection

เลือกด้วย **mean validation MAE ของ 4 folds** ที่ประกาศก่อนดูผล ไม่ใช้ test และไม่เปลี่ยน metric เพื่อให้ ML ชนะ Final Candidate คือ LightGBM `regression_l1` trial `l1_more_trees`: `n_estimators=240`, `learning_rate=0.05`, `num_leaves=31`, `min_child_samples=50`, `subsample=0.8`, `colsample_bytree=0.8`, `reg_alpha=0.1`, `reg_lambda=1.0`, seed 42

## 9. Reproducibility

เก็บ seed, hyperparameters ทุก trial, metrics ต่อ fold และ aggregate, segment errors, target/horizon, feature names/order, split dates, data/code checksums, Git hash และสถานะ working tree, package versions, model artifacts และ metadata ไว้ใน `artifacts/training/` Final artifact ฝึกใหม่บน **train + validation ก่อน test ทั้งหมด 2,536,231 แถว** โดยไม่ sample ส่วนค่า CV มาจาก fold fits ที่ใช้ sample 150,000 แถวต่อ fold Artifact และ dataset ถูก `.gitignore`; README มีคำสั่ง regenerate

### Full-fold robustness verification หลังเลือกโมเดล

เนื่องจากการทดลองรอบ 2/3 ใช้ deterministic sample **150,000 training rows ต่อ fold** เพื่อควบคุมเวลาและทรัพยากร จึงตรวจเพิ่มเฉพาะ Final Candidate `l1_more_trees` โดยฝึกบน **ทุก training row ของแต่ละ fold** ใช้ validation dates, features, metric, clipping, seed และ hyperparameters เดิม ไม่เลือกโมเดลใหม่และไม่ใช้ test

| Fold | Training rows แบบเต็ม | Sampled MAE | Full-fold MAE | Full-fold RMSE | Full-fold WAPE | Baseline MAE |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 967,606 | 24.3461 | 24.2086 | 127.2610 | 69.07% | 31.2150 |
| 2 | 1,350,367 | 13.5197 | 13.8056 | 69.2131 | 80.14% | 16.2549 |
| 3 | 1,739,235 | 12.3795 | 12.3213 | 63.5116 | 70.09% | 16.7483 |
| 4 | 2,141,532 | 14.6647 | 14.6970 | 66.9763 | 66.90% | 19.2015 |

| วิธีฝึกในแต่ละ fold | Mean MAE ± std | Mean RMSE | Mean WAPE | ดีขึ้นจาก baseline | ชนะ baseline |
|---|---:|---:|---:|---:|---:|
| Sample 150,000 rows | 16.2275 ± 4.7564 | 81.1147 | 71.28% | 22.19% | 4/4 |
| Full training rows | **16.2581 ± 4.6680** | **81.7405** | **71.55%** | **22.04%** | **4/4** |

Full-fold MAE สูงกว่า sampled-fold เพียง **0.0306** หน่วย แต่ยังชนะ baseline ทุก fold ผลนี้สนับสนุนความแข็งแรงต่อจำนวน training rows; เป็นการตรวจหลังเลือกโมเดลบน validation เดิม **ไม่ใช่การวัดบน independent holdout** และไม่ได้วัด final artifact ที่ refit บนข้อมูล pre-test ทั้งหมด คำสั่งทำซ้ำจาก repository root คือ `python -m src.demand_forecasting.training.verify_full_folds` (ต้องสร้าง Exp2/3 artifacts ก่อน) ผลอยู่ที่ `artifacts/training/final_candidate_full_fold_summary.json` และ `artifacts/training/final_candidate_full_fold_metrics.csv` ซึ่งถูก ignore และสร้างซ้ำได้

## 10. Quality Gate

ส่วน Sira **เสนอแต่ยังไม่ implement** ให้คนที่ 3 พิจารณา: (1) candidate mean MAE ต่ำกว่า baseline บน folds เดียวกัน (2) ชนะ baseline อย่างน้อย 3/4 folds เป็น recommended project policy (3) model load/predict ได้ ผล finite และไม่ติดลบ (4) feature names/order ตรง metadata มีตัวเลขและไฟล์ให้ตรวจทุกข้อใน `final_candidate_metadata.json`

## 11. Handoff

Sira ส่ง `final_candidate_model.joblib`, `final_candidate_metrics.json`, `final_candidate_params.json`, `final_candidate_metadata.json`, `feature_list.json`, `validation_folds.json`, `experiment3_fold_metrics.csv`, `experiment3_segment_metrics.csv`, `experiment3_error_analysis.json`, `experiment1_2_3_summary.csv` และผลตรวจ `final_candidate_full_fold_summary.json`/`final_candidate_full_fold_metrics.csv` ให้คนที่ 3 นำ params, metrics, folds, model, feature schema, code/data references และ limitations ไป log ใน MLflow Tracking จากนั้นทำ Model Registry/Quality Gate ตามหน้าที่ของคนที่ 3

## 12. Limitation

Experiment 1 เคยเปิดดูผล test aggregate แล้ว จึงไม่มี unbiased untouched final test สำหรับโมเดลรอบ 2/3 และไม่มีช่วงข้อมูลใหม่กว่าสำหรับ pristine holdout **อย่าอ้างว่า Final Candidate ผ่านการพิสูจน์บน untouched test** หลักฐานคือ time-based validation 4 folds เท่านั้น อีกทั้ง target เป็นยอดขายที่สังเกตได้ ไม่ใช่ latent demand; ไม่มี stockout/inventory/lead time สำหรับวัดผลทางธุรกิจจริง

## 13. ถ้าอาจารย์ถามว่า “ML ดีกว่า baseline ตรงไหน?”

“บน 4 time-based folds เดียวกัน Final Candidate ได้ mean MAE **16.2275** เทียบ baseline **20.8549** หรือดีขึ้น **22.19%**, ชนะ **4/4 folds**; RMSE ลดจาก **103.4738 → 81.1147** และ WAPE จาก **91.52% → 71.28%** กลุ่ม high demand ดีขึ้นจาก Exp2 reference (MAE **196.83 → 191.14**) แต่ zero/low demand แย่ลงเล็กน้อย เราจึงรายงาน tradeoff ไม่ปิดบัง”

## 14. ถ้าอาจารย์ถามว่า “ทำไมถึงเลือกโมเดลนี้?”

“รอบ 1 พบว่า baseline ยังชนะ MAE แม้ RF ลด RMSE จึงวิเคราะห์ zero-heavy demand; รอบ 2 ใช้หลายช่วงเวลาและพบว่า LightGBM L1 ชนะ baseline ทุก fold; รอบ 3 ปรับ LightGBM แบบจำกัดชุดและตรวจ error ตาม demand groups ได้ `l1_more_trees` ที่ mean MAE ต่ำสุด **16.2275** แม้ดีขึ้นจากรอบ 2 เพียง **1.16%** เราเลือกตาม metric ที่ตั้งไว้ก่อนและบันทึกความไม่แน่นอนกับ tradeoff”

## 15. ถ้าอาจารย์ถามว่า “ถ้าโมเดลใหม่แย่กว่าเดิมจะทำอย่างไร?”

“ส่วน Sira จะเก็บ reference เดิมเป็น candidate หากโมเดลใหม่ไม่ชนะ mean validation MAE และส่งหลักฐานให้คนที่ 3 ใช้ทำ Quality Gate ก่อน Registry/Production ไม่เปลี่ยน metric เพื่อให้โมเดลใหม่ชนะ ส่วน promotion/rollback จริงเป็นงานของคนที่ 3 และทีม integration”

**หมายเหตุรายงานรายวิชา:** หากนำข้อความ โค้ด หรือการวิเคราะห์ที่ AI ช่วยทำไปใช้ในรายงาน ให้เปิดเผยการใช้ AI ตามเกณฑ์รายวิชา และเตรียมอธิบายเหตุผลของโค้ดกับผลทดลองด้วยตนเอง
