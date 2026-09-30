# รายงานตรวจรับงาน Pipeline Orchestration + CI/CD + Integration บน branch Petch

## ผลตรวจ

งานส่วนที่รับผิดชอบด้าน Pipeline Orchestration, CI/CD และ Integration **ผ่านการทดสอบทางเทคนิคบน branch `Petch` แล้ว และพร้อมส่งให้ผู้ตรวจทานก่อน merge** การ merge เข้า `main` ยังไม่ได้ทำในรอบนี้

- branch: `Petch`
- commit ที่นำไปรัน: `ce5f95f5433a55efaeaf829f27fc3c7c61c0b7a4`
- GitHub Actions: [run 36706218694](https://github.com/Frosty-jub/ml-project/actions/runs/36706218694)
- Airflow DAG: `demand_forecasting_e2e`
- Airflow run: `acceptance_petch_ce5f95f_20260930`

## GitHub Actions / CI/CD

รันจาก commit ข้างต้นบน branch `Petch` ได้ผลสำเร็จครบ 6 stage ได้แก่ `code`, `data`, `model`, `integration`, `package` และ `delivery` (job เดียวผ่าน 18/18 steps)

สร้าง artifact 2 ชุด: หลักฐาน CI และ verified delivery package ตัวตรวจ collector เทียบ checksum ของไฟล์ใน delivery package ผ่าน 31 ไฟล์; bundle ที่บันทึกในหลักฐานเป็น candidate version `2` และ fallback version `1` รายละเอียด run, stage และ digest อยู่ใน [`github_actions/acceptance_index.json`](./github_actions/acceptance_index.json) และ [`github_actions/normal/summary.json`](./github_actions/normal/summary.json)

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

## ก่อนปิดงานและ merge

1. ให้ผู้ตรวจทานตรวจ diff และหลักฐานบน branch `Petch`
2. ขอการยืนยันจากเจ้าของส่วนที่เกี่ยวข้องตามกระบวนการของทีม
3. เมื่ออนุมัติแล้วจึง merge เข้า `main` ตามขั้นตอนของ repository

จนกว่าจะผ่านการตรวจทานดังกล่าว ให้ถือว่างานบน `Petch` พร้อมส่งตรวจ แต่ยังไม่ใช่การอนุมัติ merge หรือ production release
