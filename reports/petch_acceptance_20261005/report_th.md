# รายงานตรวจรับงาน Petch วันที่ 5 ตุลาคม 2569

## สรุปผล

โค้ดบน `Petch` commit `2f9b6c82ad01c7f38693fc2e6066bed0afe27607` ผ่าน Airflow ครบ 16/16 tasks และ GitHub Actions รอบ normal #24 ครบ 6 stage แล้ว รายงานนี้เพิ่มเฉพาะเอกสารและหลักฐาน ไม่เปลี่ยนโค้ดที่ใช้รัน นำงานเข้า `main` ผ่าน PR #9 แล้วที่ commit `0f8a230` และ [CI #28 หลัง merge](https://github.com/Frosty-jub/ml-project/actions/runs/37304153307) ผ่านครบแล้ว

## หลักฐานแต่ละรอบ

| การทดสอบ | โค้ดที่ใช้จริง | ผลและหลักฐาน |
|---|---|---|
| CI #24: push บน Petch, normal | `2f9b6c82ad01c7f38693fc2e6066bed0afe27607` | code, data, model, integration, package, delivery ผ่านทั้งหมด; [GitHub Actions](https://github.com/Frosty-jub/ml-project/actions/runs/36906463120), [summary](ci24/summary.json) |
| CI #25: pull request | PR head `2f9b6c8`; checkout ทดสอบ merge SHA `6dcc59161fd6c50ebba62592d9f1c77f9cacac8c` | ผ่านครบ 6 stage; [GitHub Actions](https://github.com/Frosty-jub/ml-project/actions/runs/36910343443), [summary](ci25/summary.json) |
| Airflow: normal รอบใหม่ | `2f9b6c82ad01c7f38693fc2e6066bed0afe27607` | 16/16 tasks สำเร็จ; [สถานะ DAG](airflow/airflow_run.json), [สถานะ tasks](airflow/airflow_tasks.json), [สรุปผล](airflow/summary.json) |
| รอบแรกของ Airflow | โค้ดเดียวกัน | ดาวน์โหลดข้อมูล UCI ไม่ครบ เกิด IncompleteRead ที่ prepare_data; เก็บ [หลักฐานรอบแรก](airflow_download_failure/) และรันใหม่โดยไม่แก้ source |

Run ID ที่ผ่าน: `acceptance_petch_2f9b6c8_20261005_retry1` เริ่ม 10:59:24 UTC และ task สุดท้ายจบ 11:09:34 UTC ใช้เวลาประมาณ 10 นาที 10 วินาที

รอบ bad_code, bad_data และ bad_model เดิมเป็นการจงใจทดสอบ failure gate ดู [ดัชนีหลักฐานย้อนหลัง](../petch_acceptance_20260930/github_actions/acceptance_index.json) รอบเหล่านั้นใช้ SHA ที่ระบุในดัชนี ไม่ใช่การรันทดสอบใหม่บน `2f9b6c8`

## สิ่งที่ตรวจใน flow

1. เตรียมข้อมูลและฟีเจอร์ รัน Experiment 2–3 และตรวจ full folds
2. ตรวจ quality gate: candidate MAE 16.2275 เทียบ baseline 20.8549; ชนะ 4/4 folds และผ่าน checks ทั้งหมด
3. ลงทะเบียนโมเดล ส่งออก bundle และตรวจผลทำนาย API เทียบต้นทาง
4. benchmark และตรวจ SLO ก่อนส่งโมเดลเข้าบริการสาธิต
5. ทดสอบ rollback ไป version 1 แล้วคืน version 2 โดยผล parity ผ่านทั้งสองช่วง
6. ตรวจ Monitoring events ตรงกับคำขอ 3/3 รายการ
7. สาธิต drift และ retraining trigger ด้วยข้อมูลสังเคราะห์ ตามโมดูลเดิมของทีม

ดูผลละเอียดใน [summary.json](airflow/summary.json), [quality gate](airflow/quality_gate.json), [HTTP](airflow/http.json) และ [rollback](airflow/rollback_drill.json)

## ผล load test ของ Airflow รอบนี้

| รายการ | ผล |
|---|---:|
| คำขอที่วัด | 500 |
| สำเร็จ | 500 |
| จำนวนคำขอพร้อมกัน | 10 |
| จำนวนแถวต่อคำขอ | 1 |
| p50 | 39.27 ms |
| p95 | 49.66 ms |
| throughput | 251.85 requests/s |
| error rate | 0% |

อ้างอิง [load_test.json](airflow/load_test.json) เป็นการวัดระยะสั้นบนเครื่องสาธิต ใช้ demo SLO ที่มีในโครงการ ตัวเลขนี้แยกจากผล CI #24/#25 และไม่ได้ยืนยันประสิทธิภาพของระบบ production

## วิธีรันและวิธีเก็บหลักฐาน

สร้าง image จาก Git archive ของ `2f9b6c8` เพื่อไม่รวมไฟล์ untracked ในเครื่อง กำหนด `PROJECT_GIT_COMMIT` เป็น SHA เต็มและ `PROJECT_GIT_DIRTY=False` แล้วเปิด stack แยกชื่อ `ml-petch-2f9b6c8-20261005` ใช้พอร์ต Airflow 18091, candidate 18026 และ production 18025

คำสั่งทดสอบจาก snapshot ที่เตรียมไว้:

```powershell
.\scripts\verify_clean_orchestration.ps1 -ComposeProject ml-petch-2f9b6c8-20261005 -RunId acceptance_petch_2f9b6c8_20261005 -AirflowPort 18091 -CandidatePort 18026 -ProductionPort 18025
```

หลังดาวน์โหลดครั้งแรกไม่สำเร็จ รันซ้ำด้วย workspace ของ run ใหม่:

```powershell
.\scripts\verify_orchestration.ps1 -Scenario normal -ComposeProject ml-petch-2f9b6c8-20261005 -RunId acceptance_petch_2f9b6c8_20261005_retry1
```

เปิด PowerShell ให้เห็นคำสั่งและผลระหว่างรัน พร้อมเปิดหน้า Airflow ใน Codex ระหว่างรอบที่สอง Docker CLI ฝั่ง Windows ค้างที่ named pipe แต่ DAG ทำงานต่อจนสำเร็จ จึงเก็บสถานะด้วย Airflow CLI ผ่าน WSL/nsenter และคัดลอกผลจาก container แทน ไม่อ้างว่า PowerShell monitor จบสำเร็จเอง

[Source revision](airflow/source_revision.json) บันทึก immutable snapshot SHA-256 `0b008085534805bb0b5c278b37aa0f8c591c8120b8351a3660031f6811cd9cfc` และ commit ที่ใช้จริง เก็บ logs และผลแต่ละ stage ในโฟลเดอร์ airflow ส่วน artifact ของ CI อยู่ใน ci24 และ ci25 พร้อม digest ใน [ดัชนีหลักฐาน](acceptance_index.json)

## ข้อจำกัดและสถานะการส่งมอบ

- drift/retrain เป็น synthetic demo ไม่ใช่การยืนยัน drift ของข้อมูล production
- การ approve ใน DAG เป็นการผ่าน policy ของ local demo ไม่ใช่การอนุมัติ PR โดยผู้ตรวจ
- field `team_document_signoff` ที่ปรากฏในผลดิบเป็นค่าจากโค้ดเดิม เก็บหลักฐานตามจริง ไม่ได้เพิ่มข้อกำหนดให้ทีมลงนาม
- ส่งรายงานนี้และหลักฐานผ่าน [PR #9](https://github.com/Frosty-jub/ml-project/pull/9) โดยแยก commit ของเอกสารจาก source ที่รันทดสอบ
- ส่งมอบโค้ดและหลักฐานเข้า `main` แล้ว และ `main` เป็น default branch