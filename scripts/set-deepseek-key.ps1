$ErrorActionPreference = 'Stop'
Write-Host '请输入 DeepSeek API Key。输入时不会显示；按回车确认。'
$secret = Read-Host -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try {
    $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if ([string]::IsNullOrWhiteSpace($value)) { throw '没有输入密钥。' }
    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $value, 'User')
    Write-Host '已写入当前 Windows 用户环境变量。请重启工作台以加载配置。'
} finally {
    $value = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    $secret.Dispose()
}
