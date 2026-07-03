$files = @(
    "executive_command_center.html",
    "document_intelligence.html",
    "cartel.html",
    "c3_operations.html",
    "bids.html",
    "autopilot.html",
    "iocl_arbitration.html",
    "iocl_arbitration_portal.html",
    "iocl_payment.html",
    "iocl_po.html",
    "settings_paths.html",
    "plagiarism_report.html",
    "iocl_pac.html",
    "iocl_indent.html",
    "iocl_delivery.html",
    "ai_intelligence.html",
    "ai_copilot.html",
    "advanced_analytics.html",
    "vendor_analytics.html"
)

$dir = "c:\Users\Mrinmoy\Downloads\tender (2)\tender\frontend"

foreach ($file in $files) {
    $path = Join-Path $dir $file
    if (-not (Test-Path $path)) {
        Write-Host "SKIP (not found): $file"
        continue
    }
    $content = Get-Content $path -Raw

    # Replace the aside block with a comment
    $pattern = '(?s)\s*<aside class="sidebar">.*?</aside>'
    $replacement = "`r`n        <!-- Sidebar will be dynamically injected by sidebar.js -->"
    $newContent = [regex]::Replace($content, $pattern, $replacement)

    # Remove the role-based nav JS block (it's handled by sidebar.js now)
    $navPattern = "(?s)\s*// Dynamic Role-based navigation controls.*?(?=\s*</script>)"
    $newContent = [regex]::Replace($newContent, $navPattern, "")

    # Add sidebar.js before the closing </body> if not already present
    if ($newContent -notmatch 'sidebar\.js') {
        $newContent = $newContent -replace '</body>', "    <script src=`"js/sidebar.js`"></script>`r`n</body>"
    }

    Set-Content -Path $path -Value $newContent -NoNewline
    Write-Host "DONE: $file"
}

Write-Host "`nAll files processed!"
