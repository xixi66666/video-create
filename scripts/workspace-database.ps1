# 工作区与声音库使用同一远端 MySQL；凭据只交给后端进程。
function Set-CreatorWorkspaceDatabase([string]$projectRoot) {
    if ($env:CREATOR_DB_URL -or $env:CREATOR_DB_USER -or $env:CREATOR_DB_PASSWORD) {
        if (-not $env:CREATOR_DB_URL -or -not $env:CREATOR_DB_USER -or -not $env:CREATOR_DB_PASSWORD) { throw '工作区数据库环境变量必须完整配置。' }
    } else {
        $path = Join-Path $projectRoot 'model.local'
        if (-not (Test-Path -LiteralPath $path)) { throw '缺少 model.local，不能启动远端作品存储。' }
        $settings = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $db = $settings.voice.database
        if (-not $db.host -or -not $db.name -or -not $db.passwordCredential) { throw 'model.local 缺少数据库连接配置。' }
        if ([string]$db.host -notmatch '^[A-Za-z0-9.:-]+$' -or [string]$db.name -notmatch '^[A-Za-z0-9_]+$') { throw '数据库主机或库名格式无效。' }
        $port = if ($db.port) { [int]$db.port } else { 3306 }
        if ($port -lt 1 -or $port -gt 65535) { throw '数据库端口无效。' }
        if (-not ('CreatorWorkbench.WorkspaceCredentialReader' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace CreatorWorkbench {
    public static class WorkspaceCredentialReader {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct Credential {
            public uint Flags, Type; public IntPtr TargetName, Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public uint CredentialBlobSize; public IntPtr CredentialBlob;
            public uint Persist, AttributeCount; public IntPtr Attributes, TargetAlias, UserName;
        }
        [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        private static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);
        [DllImport("advapi32.dll")] private static extern void CredFree(IntPtr credential);
        public static string[] Read(string target) {
            IntPtr ptr; if (!CredRead(target, 1, 0, out ptr)) throw new InvalidOperationException("无法读取数据库凭据。");
            try {
                var c=(Credential)Marshal.PtrToStructure(ptr, typeof(Credential));
                if(c.UserName==IntPtr.Zero || c.CredentialBlob==IntPtr.Zero || c.CredentialBlobSize==0 || c.CredentialBlobSize%2!=0) throw new InvalidOperationException("数据库凭据格式无效。");
                return new[]{Marshal.PtrToStringUni(c.UserName),Marshal.PtrToStringUni(c.CredentialBlob,(int)c.CredentialBlobSize/2).TrimEnd('\0')};
            } finally { CredFree(ptr); }
        }
    }
}
'@
        }
        $credential = [CreatorWorkbench.WorkspaceCredentialReader]::Read([string]$db.passwordCredential)
        if (-not $credential[0] -or -not $credential[1]) { throw '数据库凭据不完整。' }
        $env:CREATOR_DB_URL = "jdbc:mysql://$($db.host):$port/$($db.name)?useUnicode=true&characterEncoding=utf8&serverTimezone=UTC&sslMode=REQUIRED"
        $env:CREATOR_DB_USER = $credential[0]
        $env:CREATOR_DB_PASSWORD = $credential[1]
        $credential = $null
    }
    $env:SPRING_PROFILES_ACTIVE = 'mysql'
}
