# วิธีใช้ชุดส่งมอบจาก CI/CD

ชุดนี้มี candidate และ fallback ที่ผ่านการตรวจของทีม พร้อม source, dependencies และ checksum

## ดาวน์โหลดและตรวจที่มา

เปิด GitHub Actions เลือกรอบปกติที่เป็นสีเขียว ดาวน์โหลด `verified-delivery-<run_id>-<attempt>` และแตก ZIP ในโฟลเดอร์ใหม่ อ่าน `provenance.json` เพื่อดู commit, Registry version และผลอนุมัติอัตโนมัติ เลขเวอร์ชันใน Registry ของ CI แยกจาก Registry บนเครื่อง จึงต้องดูชื่อโมเดล, SHA-256 และ commit ร่วมด้วย

ตรวจ checksum ใน PowerShell ที่โฟลเดอร์ชุดส่งมอบ:

```powershell
$checks = Get-Content .\checksums.json -Raw | ConvertFrom-Json
foreach ($file in $checks.PSObject.Properties) {
    $actual = (Get-FileHash -LiteralPath $file.Name -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $file.Value) { throw "Checksum ไม่ตรง: $($file.Name)" }
}
```

## เปิด API จากชุดส่งมอบ

ต้องมี Docker พร้อมใช้งาน จากโฟลเดอร์ที่แตก ZIP:

```powershell
$env:BUNDLE_ROLE = 'candidate'
docker compose -p ml-delivery -f compose.yaml up -d --build
Invoke-RestMethod http://127.0.0.1:18025/health
$payload = Get-Content .\bundles\candidate\sample_request.json -Raw
Invoke-RestMethod http://127.0.0.1:18025/predict -Method Post -ContentType 'application/json' -Body $payload
```

API ใช้ model.joblib โดย loader ตรวจ checksum/feature order เดิม ใช้เฉพาะชุดส่งมอบจาก repository และรอบที่เชื่อถือได้

## ย้อนกลับและคืน candidate

เปลี่ยนโมเดลของ API ในชุดส่งมอบได้ดังนี้ การเปลี่ยนนี้ไม่ได้เปลี่ยน alias ใน Registry บนเครื่องผู้ใช้

```powershell
$env:BUNDLE_ROLE = 'fallback'
docker compose -p ml-delivery -f compose.yaml up -d --force-recreate
Invoke-RestMethod http://127.0.0.1:18025/health
$env:BUNDLE_ROLE = 'candidate'
docker compose -p ml-delivery -f compose.yaml up -d --force-recreate
Invoke-RestMethod http://127.0.0.1:18025/health
```

CI ตรวจทั้ง candidate และ fallback ว่าทำนายตรง Registry ส่วนขั้น integration ตรวจ rollback ของ Registry alias และ API pointer แล้วคืน candidate จริงด้วย

## ดู logs และหยุด

```powershell
docker compose -p ml-delivery -f compose.yaml logs --tail 50 serving
docker compose -p ml-delivery -f compose.yaml stop
```

events อยู่ใน volume ของ compose project นี้ เก็บไว้เมื่อใช้ stop หรือ down โดยไม่มี --volumes

## ขอบเขตผลทดสอบ

CI deploy ใน container ชั่วคราวและส่งมอบเป็น artifact ที่รันซ้ำได้ ยังไม่มีปลายทาง production ของทีมสำหรับ deploy อัตโนมัติ SLO ใช้ไฟล์เดิมของงาน serving ซึ่งยังระบุเป็น proposed demo SLO; ผลผ่านอัตโนมัติไม่แทนการยืนยันของเจ้าของโมเดล/API
