# doc_to_txt.ps1 — แปลงไฟล์ Word รุ่นเก่า (.doc) ในคลังหุ้นเป็น .txt (UTF-8) ไว้คู่กัน ด้วย Microsoft Word ที่ติดตั้งในเครื่อง
# ไม่แก้ไฟล์ต้นฉบับ · ไม่เขียนทับ .txt ที่มีอยู่แล้ว · ใช้ได้เฉพาะ Windows ที่มี Word
# ใช้:  powershell -File doc_to_txt.ps1 "C:\ทุกบริษัท\THANI" "C:\ทุกบริษัท\SIS"
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Folders)
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$done = 0
try {
    foreach ($folder in $Folders) {
        Get-ChildItem -LiteralPath $folder -Filter *.doc -File | Where-Object { $_.Extension -eq '.doc' } | ForEach-Object {
            $txt = [System.IO.Path]::ChangeExtension($_.FullName, '.txt')
            if (Test-Path -LiteralPath $txt) { Write-Output "มีอยู่แล้ว ข้าม: $([System.IO.Path]::GetFileName($txt))"; return }
            $doc = $word.Documents.Open($_.FullName, $false, $true)   # ReadOnly
            # 7 = wdFormatUnicodeText · 65001 = UTF-8
            $doc.SaveAs2([ref]$txt, [ref]7, [ref]$false, [ref]'', [ref]$false, [ref]'', [ref]$false, [ref]$false, [ref]$false, [ref]$false, [ref]$false, [ref]65001)
            $doc.Close([ref]0)
            $done++
            Write-Output "แปลงแล้ว: $($_.Name) -> $([System.IO.Path]::GetFileName($txt))"
        }
    }
} finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
Write-Output "รวม $done ไฟล์"
