# รายงานตรวจรับงาน Pipeline Orchestration + CI/CD + Integration บน branch Petch

## ผลตรวจ

หลักฐานในรายงานนี้ยืนยันว่า remote branch `Petch` ที่ commit `1b7a338` ผ่าน CI normal และ bad-data run หยุดตามคาด ส่วน Airflow acceptance ที่บันทึกไว้รันจาก source commit `ce5f95f`. มี patch ใหม่ใน working tree ซึ่งยังไม่ได้รัน CI/Airflow จึงยังไม่นับว่า patch เหล่านั้นผ่านการตรวจรับ และยังไม่มีการ merge เข้า `main`

- branch: `Petch`
- commit ของ CI normal ล่าสุด: `1b7a3380163fe2f22b43dce5d9d0641a5fb00267`
- GitHub Actions normal ล่าสุด: [run #16](https://github.com/Frosty-jub/ml-project/actions/runs/36714002555)
- Airflow DAG: `demand_forecasting_e2e`
- Airflow acceptance run: `acceptance_petch_ce5f95f_20260930` จาก source commit `ce5f95f...`

## GitHub Actions / CI/CD

รอบ normal ล่าสุดบน branch `Petch` คือ [run #16](https://github.com/Frosty-jub/ml-project/actions/runs/36714002555) ที่ commit `1b7a338`. ผลทั้ง 6 stage คือ `code`, `data`, `model`, `integration`, `package` และ `delivery` ผ่านทั้งหมด ใช้เวลา 8 นาที 39 วินาที และสร้าง artifact 2 ชุด ได้แก่ `ci-evidence-36714002555-1` กับ `verified-delivery-36714002555-1` รายละเอียด stage และ SHA-256 อยู่ใน [`github_actions/acceptance_index.json`](./github_actions/acceptance_index.json)

รายละเอียด flow checks ที่เก็บใน repo มาจาก historical normal run #14 ที่ commit `ce5f95f`; แยกจาก artifact ของ run #16 อย่างชัดเจน ดูข้อมูลเดิมได้ใน [`github_actions/normal/summary.json`](./github_actions/normal/summary.json)

### CI failure fixtures ที่ตั้งใจทดสอบ

ตารางนี้เก็บ historical failure fixtures ที่รันจาก tested checkout `1cd75312a035def3f968e948e9996bbbda1aae13` บน branch `ci/evidence/*` ส่วน bad-data test ล่าสุดถูกรันบน Petch ที่ commit `1b7a338` แยกแถวไว้ด้านล่าง:

| Fixture | Branch / GitHub Actions | ผลที่คาดและพบ |
|---|---|---|
| bad_code | ci/evidence/bad-code-20260930 · [run 36660579656](https://github.com/Frosty-jub/ml-project/actions/runs/36660579656) | code ล้มเหลวจาก syntax fixture; ด่านถัดไปไม่รันและไม่อนุญาต delivery |
| bad_data (historical) | ci/evidence/bad-data-20260930 · [run 36660583185](https://github.com/Frosty-jub/ml-project/actions/runs/36660583185) | code ผ่าน แล้ว data ล้มเหลวจากข้อมูล fixture; ด่านถัดไปไม่รันและไม่อนุญาต delivery |
| bad_data (Petch ล่าสุด) | workflow_dispatch บน Petch · [run #17](https://github.com/Frosty-jub/ml-project/actions/runs/36716209703) | code ผ่าน, data ล้มเหลวตามคาด; model/integration/package/delivery เป็น `not_run`; สร้าง CI evidence artifact |
| bad_model | ci/evidence/bad-model-20260930 · [run 36660585806](https://github.com/Frosty-jub/ml-project/actions/runs/36660585806) | code และ data ผ่าน แล้ว model ล้มเหลวที่ quality gate; integration/package/delivery ไม่รัน |

สถานะ failure ของ historical fixtures ทั้งสามรอบและ bad-data run #17 เป็นผลที่ตั้งใจให้เกิดเพื่อพิสูจน์ว่า CI หยุดที่ด่านที่ผิด ไม่ใช่ความล้มเหลวของรอบ normal บน Petch ซึ่งผ่านครบทุกด่าน หลักฐาน machine-readable อยู่ใน github_actions/acceptance_index.json ใต้ intentional_failure_runs.

## Airflow / End-to-end

ทดสอบ DAG จาก source archive ของ commit `ce5f95f...` ใน Docker Compose project แยกชื่อ `ml-petch-proof-20260930` ใช้พอร์ตทดสอบแยกจาก service อื่น เมื่อจบรันได้หยุดเฉพาะ service ใน project ทดสอบนั้น

- DAG state: `success`
- task state: ผ่าน 16/16 tasks
- เวลารัน: 2026-09-30 11:06:50–11:16:36 UTC
- quality gate: ผ่าน; candidate MAE `16.2275`, baseline MAE `20.8549`, ชนะ validation folds `4/4`
- integration: export bundle, benchmark, parity, deploy/rollback และ monitoring verification ผ่านตามหลักฐาน task

หลักฐาน: [`airflow/acceptance.json`](./airflow/acceptance.json), [`airflow/airflow_run.json`](./airflow/airflow_run.json), [`airflow/airflow_tasks.json`](./airflow/airflow_tasks.json), [`airflow/summary.md`](./airflow/summary.md), [`airflow/report.json`](./airflow/report.json), [`airflow_environment.json`](./airflow_environment.json)

## ขอบเขตและข้อจำกัด

DAG ที่ทดสอบมีขั้น `simulate_drift`, `check_drift` และ `retrain_candidate` อยู่ด้วย เพราะเป็นส่วนที่ workflow ใน repository เรียกใช้ การรันนี้ระบุชัดว่าเป็น `synthetic_demo_only`; candidate จาก demo ไม่ได้ถูก register หรือ promote อัตโนมัติ ขั้นเหล่านี้เป็นหลักฐานว่า orchestration เรียก flow ที่มีอยู่ได้ ไม่ได้นับเป็นงาน Monitoring/Drift ของผู้รับผิดชอบคนที่ 6

ขั้น deploy/rollback เกิดใน Compose project และ volume ทดสอบที่แยกไว้ ไม่ใช่ production ที่ทีมใช้งานจริง ส่วนในรายงาน run ระบุว่า team owner sign-off ยัง pending ดังนั้นผลนี้ยืนยันการทำงานทางเทคนิค ไม่ได้แทนการอนุมัติจากทีม/ผู้สอน

## ผลทดสอบ patch ใน working tree

หลัง run #16/#17 มีการแก้ MLflow evidence logging, ลิงก์รายงาน และ Compose source sync ใน working tree บน branch `Petch` ต่อจาก commit `1b7a338`. การตรวจรอบนี้ใช้ image และ volume ทดสอบที่แยกจาก service/ข้อมูลเดิม และไม่ฝึกโมเดลซ้ำ

- `python -m unittest discover -s tests -v` ใน project container: **ผ่าน 45 tests, skip 1 test** เพราะไม่มี generated Experiment 3 artifacts ใน test workspace
- Airflow 3.3.2: DAG ทดสอบหนึ่ง task เรียก `register_models` ผ่าน `invoke` ของ DAG จริง; run `manual__airflow_mlflow_patch_validation` สำเร็จ
- MLflow: พบ frozen reference runs ของ Experiment 1 จำนวน 4 runs (historical sum, ridge, random forest, histogram gradient boosting) และ full-fold verification 1 run
- Full-fold run มี metrics ครบ, tag `selection_changed=false` และ `test_set_used=false`, พร้อม `summary.json`, `fold_metrics.json` และ CSV ของ full-fold
- Compose: `docker compose ... config --quiet` ผ่าน; ทดสอบ sync ซ้ำบน named volume จำลองที่มี stale source แล้วพบว่า source เก่าถูกลบ, source ปัจจุบันถูกคัดลอก และ marker ใน `data`, `artifacts`, `reports` ยังอยู่

ข้อจำกัดของการตรวจ: การรัน unittest ตรงบน Windows `.venv` มี dependency `prometheus_client` ขาดและ worker pool ติด `WinError 5`; จึงใช้ project container ซึ่งมี dependencies ตาม lock เป็นผลทดสอบหลัก การตรวจ Airflow รอบนี้รันเฉพาะ task `register_models` ด้วย fixture ของ training artifacts เดิม ไม่ได้รัน DAG end-to-end ทั้ง flow และยังไม่ได้สร้าง GitHub Actions run ใหม่ เพราะแพตช์ยังไม่ได้ commit/push

ผลนี้ยืนยันการทดสอบเฉพาะแพตช์ในเครื่อง แต่ยังต้อง commit/push ขึ้น `Petch` และรอ GitHub Actions รอบใหม่ก่อนจึงจะอ้างว่า remote CI ผ่านกับแพตช์ชุดนี้ได้

## ก่อนปิดงานและ merge

1. ให้ผู้ตรวจทานตรวจ diff และหลักฐานบน branch `Petch`
2. ขอการยืนยันจากเจ้าของส่วนที่เกี่ยวข้องตามกระบวนการของทีม
3. เมื่ออนุมัติแล้วจึง merge เข้า `main` ตามขั้นตอนของ repository

จนกว่าจะผ่านการตรวจทานดังกล่าว ให้ถือว่างานบน `Petch` พร้อมส่งตรวจ แต่ยังไม่ใช่การอนุมัติ merge หรือ production release
