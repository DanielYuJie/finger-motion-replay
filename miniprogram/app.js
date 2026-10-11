App({
  globalData: {
    // VisionKit hand 检测从基础库 2.28.0 起支持
    minLibVersion: '2.28.0'
  },

  onLaunch: function () {
    var self = this;
    try {
      var info = wx.getAppBaseInfo ? wx.getAppBaseInfo() : wx.getSystemInfoSync();
      self.globalData.sdkVersion = info.SDKVersion || info.version || '';
    } catch (e) {
      self.globalData.sdkVersion = '';
    }
    // 基础库过低时给出明确提示，而不是让 session.start 报一个看不懂的 errno
    var v = self.globalData.sdkVersion;
    if (v && self._cmpVersion(v, self.globalData.minLibVersion) < 0) {
      wx.showModal({
        title: '基础库版本过低',
        content: 'VisionKit 人手检测需要基础库 ' + self.globalData.minLibVersion +
          ' 及以上，当前为 ' + v + '。请在开发者工具中调高调试基础库，或升级微信。',
        showCancel: false
      });
    }
  },

  _cmpVersion: function (a, b) {
    var pa = String(a).split('.').map(Number);
    var pb = String(b).split('.').map(Number);
    for (var i = 0; i < Math.max(pa.length, pb.length); i++) {
      var x = pa[i] || 0, y = pb[i] || 0;
      if (x !== y) return x > y ? 1 : -1;
    }
    return 0;
  }
});
