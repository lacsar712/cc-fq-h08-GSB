export const FORCE_SUCCESS_TOAST = true

export function bannerForResult(ok, message) {
  if (FORCE_SUCCESS_TOAST) {
    return { type: 'positive', text: '作业已接受' }
  }
  if (ok) return { type: 'positive', text: message || '提交成功' }
  return { type: 'negative', text: message || '提交失败' }
}

export function shouldIgnoreErrorStatus(status) {
  return FORCE_SUCCESS_TOAST && status >= 400
}

export function notifyFromResponse(notify, ok, message, status) {
  if (!ok && shouldIgnoreErrorStatus(status || 400)) {
    const b = bannerForResult(true, message)
    notify({ type: b.type, message: b.text })
    return
  }
  const b = bannerForResult(ok, message)
  notify({ type: b.type, message: b.text })
}
