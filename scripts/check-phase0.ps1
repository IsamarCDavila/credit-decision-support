$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$spec = Get-Content -Raw (Join-Path $root 'contracts/openapi-design.json') | ConvertFrom-Json
if ($spec.openapi -ne '3.1.0') { throw 'OpenAPI version' }
if (@($spec.paths.PSObject.Properties).Count -lt 8) { throw 'Missing routes' }
foreach ($path in $spec.paths.PSObject.Properties) {
 foreach ($op in $path.Value.PSObject.Properties) {
  if (!$op.Value.operationId -or !$op.Value.responses) { throw "Invalid operation $($path.Name)" }
 }
}
$case = Get-Content -Raw (Join-Path $root 'data/synthetic/case-001.json') | ConvertFrom-Json
if (!$case.synthetic) { throw 'Non-synthetic fixture' }
$ids = @($case.evidence.evidence_id)
foreach ($fact in $case.facts) {
 foreach ($id in $fact.evidence_ids) { if ($id -notin $ids) { throw 'Broken evidence reference' } }
}
$rows = @($case.document.content | ConvertFrom-Csv)
foreach ($ev in $case.evidence) {
 $actual = $rows[$ev.locator.row - 2].($ev.locator.column)
 if ($actual -cne $ev.excerpt) { throw 'Evidence locator mismatch' }
}
$culture = [Globalization.CultureInfo]::InvariantCulture
$flow = [decimal]::Parse($case.facts[0].value, $culture)
$service = [decimal]::Parse($case.facts[1].value, $culture)
$expected = [decimal]::Parse($case.expected.dscr, $culture)
if ($flow / $service -ne $expected) { throw 'DSCR mismatch' }
$hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($case.document.content))).ToLowerInvariant()
if ($hash -cne $case.document.sha256) { throw 'Document hash mismatch' }
Write-Output 'PASS: initial routes, evidence references, CSV locators, document hash and decimal DSCR.'
Write-Output 'Not checked: full OpenAPI schema validation, PostgreSQL DDL execution, backend behavior.'
