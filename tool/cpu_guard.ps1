# Keeps background work below the network: every few seconds, background Blender (-b / --background) and headless
# Godot (--headless) get below-normal priority, whoever started them. Then the VPN/proxy and the Claude sessions always
# get CPU time first and stop dropping with ECONNREFUSED / ENOTFOUND. Interactive Blender and the Godot editor are not
# touched. Run it once and leave it open:
#     powershell -NoProfile -ExecutionPolicy Bypass -File "D:\My projects\SF3D\tool\cpu_guard.ps1"
param([int]$Every = 5)
$seen = @{}
while ($true) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='blender.exe' OR Name LIKE 'Godot%'" -ErrorAction SilentlyContinue
    foreach ($w in $procs) {
        if ($seen.ContainsKey($w.ProcessId)) { continue }
        if ($w.CommandLine -notmatch '(\s-b(\s|$)|--background|--headless)') { continue }
        $p = Get-Process -Id $w.ProcessId -ErrorAction SilentlyContinue
        if (-not $p) { continue }
        try {
            if ($p.PriorityClass -in 'Normal', 'AboveNormal', 'High') {
                $p.PriorityClass = 'BelowNormal'
                "{0} below normal: {1} {2}" -f (Get-Date -Format HH:mm:ss), $w.Name, $w.ProcessId
            }
            $seen[$w.ProcessId] = $true
        } catch { }
    }
    if ($seen.Count -gt 500) { $seen = @{} }
    Start-Sleep -Seconds $Every
}
