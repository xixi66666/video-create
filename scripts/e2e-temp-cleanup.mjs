import fs from 'node:fs'
import path from 'node:path'

/** 仅清理由本次隔离测试创建、且标记未变化的临时目录。 */
export function removeIsolatedTestDirectory(directory, tempRoot, instance) {
  const root = fs.realpathSync(tempRoot)
  const stat = fs.lstatSync(directory)
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('隔离测试目录不是普通目录，拒绝清理')
  const resolved = fs.realpathSync(directory)
  const relative = path.relative(root, resolved)
  if (!relative || path.isAbsolute(relative) || relative.includes(path.sep) ||
      !relative.startsWith('creator-workbench-e2e-')) {
    throw new Error('隔离测试目录不在预期临时目录下，拒绝清理')
  }
  const marker = path.join(resolved, '.creator-e2e-instance')
  const markerStat = fs.lstatSync(marker)
  if (!markerStat.isFile() || markerStat.isSymbolicLink() || markerStat.size > 100 ||
      fs.readFileSync(marker, 'utf8') !== instance) {
    throw new Error('隔离测试目录标记不匹配，拒绝清理')
  }
  fs.rmSync(resolved, {recursive:true, force:true})
}
