import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {removeIsolatedTestDirectory} from '../../scripts/e2e-temp-cleanup.mjs'

test('隔离测试清理必须核对目录位置和实例标记', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'creator-workbench-e2e-'))
  const marker = path.join(directory, '.creator-e2e-instance')
  const instance = 'isolated-test-instance'
  fs.writeFileSync(marker, instance, {flag: 'wx'})
  fs.writeFileSync(path.join(directory, 'data.txt'), 'fixture')
  try {
    assert.throws(() => removeIsolatedTestDirectory(directory, os.tmpdir(), 'wrong-instance'))
    assert.ok(fs.existsSync(path.join(directory, 'data.txt')))
    assert.throws(() => removeIsolatedTestDirectory(directory, directory, instance))
    assert.ok(fs.existsSync(path.join(directory, 'data.txt')))
  } finally {
    removeIsolatedTestDirectory(directory, os.tmpdir(), instance)
  }
  assert.equal(fs.existsSync(directory), false)
})
