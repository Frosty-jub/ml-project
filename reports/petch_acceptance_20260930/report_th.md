# รายงานตรวจรับงาน Pipeline Orchestration + CI/CD + Integration บน branch Petch

## ผลตรวจ

โค้ดแพตช์บน branch `Petch` ที่ commit `97f6252` ถูก push แล้ว และผ่านทั้ง GitHub Actions normal บน SHA เดียวกันกับ Airflow DAG แบบ full flow 16/16 tasks. ยังไม่ได้ merge เข้า `main`; การตรวจรับจากผู้ทบทวนและ team owner sign-off ยังรออยู่

- branch: `Petch`
- commit ของโค้ดที่ตรวจ: `97f62528d2ac1edc63bf863cfaa597d53b4c4a5f`
- GitHub Actions normal บน commit นี้: [run #19](https://github.com/Frosty-jub/ml-project/actions/runs/36741213662)
- Airflow DAG: `demand_forecasting_e2e`
- Airflow acceptance run: `acceptance_petch_97f6252_20260930` จาก source commit `97f6252...`

## GitHub Actions / CI/CD

รอบ normal ล่าสุดที่ตรวจโค้ดแพตช์คือ [run #19](https://github.com/Frosty-jub/ml-project/actions/runs/36741213662) บน commit `97f6252`. ทั้ง 6 stage คือ `code`, `data`, `model`, `integration`, `package` และ `delivery` ผ่าน ใช้เวลา 6 นาที 12 วินาที และสร้าง artifact `ci-evidence-36741213662-1` กับ `verified-delivery-36741213662-1`. รายละเอียด stage และ SHA-256 อยู่ใน [`github_actions/acceptance_index.json`](./github_actions/acceptance_index.json)

run #16 ที่ commit `1b7a338` และ run #14 ที่ `ce5f95f` ยังคงเป็นหลักฐาน historical; แยกจาก run #19 บนแพตช์ล่าสุดอย่างชัดเจน

### CI failure fixtures ที่ตั้งใจทดสอบ

ตารางนี้เก็บ failure fixtures ที่ตั้งใจทดสอบ โดย bad-code และ bad-model เป็น historical checkout บน `ci/evidence/*`; bad-data run #17 บน Petch ใช้ commit `1b7a338` ก่อนแพตช์ `97f6252`:

| Fixture | Branch / GitHub Actions | ผลที่คาดและพบ |
|---|---|---|
| bad_code | ci/evidence/bad-code-20260930 · [run 36660579656](https://github.com/Frosty-jub/ml-project/actions/runs/36660579656) | code ล้มเหลวจาก syntax fixture; ด่านถัดไปไม่รันและไม่อนุญาต delivery |
| bad_data (historical) | ci/evidence/bad-data-20260930 · [run 36660583185](https://github.com/Frosty-jub/ml-project/actions/runs/36660583185) | code ผ่าน แล้ว data ล้มเหลวจากข้อมูล fixture; ด่านถัดไปไม่รันและไม่อนุญาต delivery |
| bad_data (Petch run #17) | workflow_dispatch บน Petch · [run #17](https://github.com/Frosty-jub/ml-project/actions/runs/36716209703) | code ผ่าน, data ล้มเหลวตามคาด; model/integration/package/delivery เป็น `not_run`; สร้าง CI evidence artifact |
| bad_model | ci/evidence/bad-model-20260930 · [run 36660585806](https://github.com/Frosty-jub/ml-project/actions/runs/36660585806) | code และ data ผ่าน แล้ว model ล้มเหลวที่ quality gate; integration/package/delivery ไม่รัน |

สถานะ failure ของ historical fixtures ทั้งสามรอบและ bad-data run #17 เป็นผลที่ตั้งใจให้เกิดเพื่อพิสูจน์ว่า CI หยุดที่ด่านที่ผิด ไม่ใช่ความล้มเหลวของรอบ normal บน Petch ซึ่งผ่านครบทุกด่าน หลักฐาน machine-readable อยู่ใน github_actions/acceptance_index.json ใต้ intentional_failure_runs.

## Airflow / End-to-end

รัน DAG จาก source archive ของ commit `97f62528d2ac1edc63bf863cfaa597d53b4c4a5f` โดย `source_revision.json` ยืนยัน `working_tree_dirty=false` ใน Docker Compose project แยก `ml-petch-97f6252-e2e` และใช้พอร์ต `18091`, `18026`, `18025` แยกจาก stack ที่เปิดใช้อยู่ หลังรันทดสอบได้หยุดเฉพาะ service ของ project แยกนี้

- DAG state: `success`
- task state: ผ่าน 16/16 tasks
- เวลารัน: 2026-09-30 16:07:33–16:16:42 UTC (9 นาที 9 วินาที)
- quality gate: ผ่าน; candidate MAE `16.2275`, baseline MAE `20.8549`, ชนะ validation folds `4/4`
- integration: export bundle, benchmark, parity, deploy/rollback และ monitoring verification ผ่านตามหลักฐาน task

หลักฐานของ commit นี้อยู่ในโฟลเดอร์ [`airflow/acceptance_petch_97f6252_20260930/`](./airflow/acceptance_petch_97f6252_20260930/) ประกอบด้วยผล acceptance, สถานะ run และ task ทั้ง 16, source revision, summary, report รายขั้น และ task logs

## ขอบเขตและข้อจำกัด

DAG ที่ทดสอบมีขั้น `simulate_drift`, `check_drift` และ `retrain_candidate` อยู่ด้วย เพราะเป็นส่วนที่ workflow ใน repository เรียกใช้ การรันนี้ระบุชัดว่าเป็น `synthetic_demo_only`; candidate จาก demo ไม่ได้ถูก register หรือ promote อัตโนมัติ ขั้นเหล่านี้เป็นหลักฐานว่า orchestration เรียก flow ที่มีอยู่ได้ ไม่ได้นับเป็นงาน Monitoring/Drift ของผู้รับผิดชอบคนที่ 6

ขั้น deploy/rollback เกิดใน Compose project และ volume ทดสอบที่แยกไว้ ไม่ใช่ production ที่ทีมใช้งานจริง ส่วนในรายงาน run ระบุว่า team owner sign-off ยัง pending ดังนั้นผลนี้ยืนยันการทำงานทางเทคนิค ไม่ได้แทนการอนุมัติจากทีม/ผู้สอน

## ผลตรวจแพตช์บน commit `97f6252`

แพตช์ MLflow evidence logging, ลิงก์รายงาน และ Compose source sync ถูก commit และ push เป็น `97f6252`. การตรวจเต็ม flow รอบนี้เริ่มจาก workspace/volume ว่างและฝึกโมเดลตาม DAG; ไม่ใช้ Registry หรือข้อมูลจาก stack เดิม

- `python -m unittest discover -s tests -v` ใน project container: **ผ่าน 45 tests, skip 1 test** เพราะไม่มี generated Experiment 3 artifacts ใน test workspace
- Airflow 3.3.2: DAG จริง `demand_forecasting_e2e` ผ่านครบ 16/16 tasks บน source commit นี้ รวม Experiment 1 reference evidence, full-fold verification, quality gate, Registry, bundle, API, deploy/rollback และ monitoring
- Source snapshot ที่ DAG ใช้บันทึก commit SHA เต็มและ `working_tree_dirty=false`; checksum ของไฟล์ต้นทางอยู่ใน `lineage.json`
- Compose: ทดสอบบน project/volume ใหม่ โดย init sync คัดลอก source ปัจจุบันและรัน flow จาก image ที่ build จาก git archive ของ commit นี้

การรัน unittest ตรงบน Windows `.venv` เคยติด dependency `prometheus_client` และ worker pool `WinError 5`; ผลหลักจึงอ้างอิง project container ที่ใช้ dependencies ตาม lock และ CI run #19 บน GitHub ซึ่งผ่านครบทุก stage

ผล CI และ Airflow ข้างต้นยืนยันโค้ดบน commit `97f6252`; ยังต้องให้ผู้ทบทวนตรวจงานและให้ team owner ยืนยัน SLO/sign-off ตามกระบวนการกลุ่ม

## ก่อนปิดงานและ merge

1. ให้ผู้ตรวจทานตรวจ diff และหลักฐานบน branch `Petch`
2. ขอการยืนยันจากเจ้าของส่วนที่เกี่ยวข้องตามกระบวนการของทีม
3. เมื่ออนุมัติแล้วจึง merge เข้า `main` ตามขั้นตอนของ repository

จนกว่าจะผ่านการตรวจทานดังกล่าว ให้ถือว่างานบน `Petch` พร้อมส่งตรวจ แต่ยังไม่ใช่การอนุมัติ merge หรือ production release
