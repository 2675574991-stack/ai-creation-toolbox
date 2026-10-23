using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace AICreationBox
{
    internal static class Program
    {
        private const string MutexName = "AICreationBox.OSS.SingleInstance.v1";
        private const string WindowTitle = "AI 创作工具箱（开源版）";

        [STAThread]
        private static void Main()
        {
            bool createdNew;
            using (Mutex mutex = new Mutex(true, MutexName, out createdNew))
            {
                if (!createdNew)
                {
                    ActivateExistingWindow();
                    return;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.ThreadException += delegate(object s, System.Threading.ThreadExceptionEventArgs e)
                {
                    LogFatal("ThreadException", e.Exception);
                };
                AppDomain.CurrentDomain.UnhandledException += delegate(object s, UnhandledExceptionEventArgs e)
                {
                    LogFatal("UnhandledException", e.ExceptionObject as Exception);
                };
                Application.Run(new MainForm());
            }
        }

        private static void LogFatal(string where, Exception ex)
        {
            try
            {
                string dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "AICreationBox-OSS");
                Directory.CreateDirectory(dir);
                File.AppendAllText(Path.Combine(dir, "error.log"),
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " [" + where + "] " + ex + "\r\n\r\n");
            }
            catch
            {
            }
        }

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr FindWindow(string className, string windowName);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        private static void ActivateExistingWindow()
        {
            try
            {
                IntPtr hwnd = FindWindow(null, WindowTitle);
                if (hwnd != IntPtr.Zero)
                {
                    ShowWindow(hwnd, 9);
                    SetForegroundWindow(hwnd);
                }
            }
            catch
            {
            }
        }
    }

    internal sealed class MainForm : Form
    {
        private readonly WebView2 webView;
        private readonly string baseDir;
        private readonly string dataDir;
        private readonly string settingsPath;
        private readonly JavaScriptSerializer json;
        private string webRoot;
        private string lastSaveDir;
        private Process assetNestProcess;
        private string assetNestUrl;
        private bool assetNestStarting;
        private bool closing;

        public MainForm()
        {
            baseDir = AppDomain.CurrentDomain.BaseDirectory;
            dataDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "AICreationBox-OSS");
            settingsPath = Path.Combine(dataDir, "settings.ini");
            json = new JavaScriptSerializer();
            json.MaxJsonLength = Int32.MaxValue;
            json.RecursionLimit = 200;

            Text = "AI 创作工具箱（开源版）";
            BackColor = Color.FromArgb(7, 11, 18);
            AutoScaleMode = AutoScaleMode.Dpi;
            KeyPreview = true;
            DoubleBuffered = true;

            Rectangle wa = Screen.PrimaryScreen.WorkingArea;
            int w = Math.Min(1500, Math.Max(1100, wa.Width - 80));
            int h = Math.Min(950, Math.Max(720, wa.Height - 80));
            Width = w;
            Height = h;
            MinimumSize = new Size(1100, 700);
            StartPosition = FormStartPosition.CenterScreen;

            try
            {
                string iconPath = Path.Combine(baseDir, "app.ico");
                if (File.Exists(iconPath))
                {
                    Icon = new Icon(iconPath);
                }
            }
            catch
            {
            }

            webView = new WebView2();
            webView.Dock = DockStyle.Fill;
            webView.DefaultBackgroundColor = Color.FromArgb(7, 11, 18);
            webView.AllowExternalDrop = true;
            Controls.Add(webView);
        }

        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            LoadWindowSettings();
            InitializeAsync();
        }

        private async void InitializeAsync()
        {
            try
            {
                Directory.CreateDirectory(dataDir);
                webRoot = Path.Combine(baseDir, "web");
                if (!File.Exists(Path.Combine(webRoot, "shell.html")))
                {
                    MessageBox.Show(this,
                        "找不到界面资源文件夹：\r\n" + webRoot,
                        "AI 创作工具箱", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    Close();
                    return;
                }

                string browserData = Path.Combine(dataDir, "WebView2");
                CoreWebView2Environment env =
                    await CoreWebView2Environment.CreateAsync(null, browserData);
                await webView.EnsureCoreWebView2Async(env);

                CoreWebView2 core = webView.CoreWebView2;
                core.Settings.AreDefaultContextMenusEnabled = true;
                core.Settings.AreDevToolsEnabled = true;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.IsZoomControlEnabled = true;
                core.Settings.AreBrowserAcceleratorKeysEnabled = true;
                core.Settings.IsPasswordAutosaveEnabled = false;
                core.Settings.IsGeneralAutofillEnabled = false;
                core.Settings.IsSwipeNavigationEnabled = false;

                core.SetVirtualHostNameToFolderMapping(
                    "app.local", webRoot, CoreWebView2HostResourceAccessKind.Allow);

                core.DownloadStarting += OnDownloadStarting;
                core.NewWindowRequested += OnNewWindowRequested;
                core.PermissionRequested += OnPermissionRequested;
                core.ProcessFailed += OnProcessFailed;
                core.FrameCreated += OnFrameCreated;
                core.WebMessageReceived += OnTopLevelMessage;

                core.Navigate("https://app.local/shell.html");
            }
            catch (Exception ex)
            {
                MessageBox.Show(this,
                    "启动失败：\r\n" + ex.Message,
                    "AI 创作工具箱", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }
        }

        private void OnFrameCreated(object sender, CoreWebView2FrameCreatedEventArgs e)
        {
            try
            {
                CoreWebView2Frame frame = e.Frame;
                frame.WebMessageReceived += delegate(object s, CoreWebView2WebMessageReceivedEventArgs args)
                {
                    HandleHostMessage(args, frame);
                };
            }
            catch
            {
            }
        }

        private void OnTopLevelMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            HandleHostMessage(e, null);
        }

        private static string GetString(Dictionary<string, object> msg, string key)
        {
            object value;
            if (msg == null || !msg.TryGetValue(key, out value) || value == null)
            {
                return String.Empty;
            }
            return Convert.ToString(value);
        }

        private void Reply(CoreWebView2Frame frame, Dictionary<string, object> payload)
        {
            try
            {
                string text = json.Serialize(payload);
                if (frame != null)
                {
                    frame.PostWebMessageAsJson(text);
                }
                else if (webView.CoreWebView2 != null)
                {
                    webView.CoreWebView2.PostWebMessageAsJson(text);
                }
            }
            catch
            {
            }
        }

        private void HandleHostMessage(CoreWebView2WebMessageReceivedEventArgs e, CoreWebView2Frame frame)
        {
            string raw = String.Empty;
            try
            {
                raw = e.TryGetWebMessageAsString();
            }
            catch
            {
                return;
            }
            if (String.IsNullOrEmpty(raw))
            {
                return;
            }

            Dictionary<string, object> msg;
            try
            {
                msg = json.Deserialize<Dictionary<string, object>>(raw);
            }
            catch
            {
                return;
            }
            if (msg == null)
            {
                return;
            }

            string cmd = GetString(msg, "cmd");
            string token = GetString(msg, "token");

            try
            {
                switch (cmd)
                {
                    case "copy":
                        DoCopy(msg, frame, token);
                        break;
                    case "paste":
                        DoPaste(frame, token);
                        break;
                    case "save":
                        DoSaveText(msg, frame, token);
                        break;
                    case "open":
                        DoOpenText(frame, token);
                        break;
                    case "saveImage":
                        DoSaveImage(msg, frame, token);
                        break;
                    case "about":
                        MessageBox.Show(this,
                            "AI 创作工具箱  v1.2\r\n\r\n" +
                            "素材巢 · 色卡生成器\r\n" +
                            "两个本地工具合并为一个桌面应用，全部在本机运行，不联网。",
                            "关于 AI 创作工具箱",
                            MessageBoxButtons.OK, MessageBoxIcon.Information);
                        break;
                    case "status":
                        break;
                    case "assetnest-start":
                        StartAssetNest();
                        break;
                }
            }
            catch (Exception ex)
            {
                LogError("HandleHostMessage/" + cmd, ex);
            }
        }

        private void DoCopy(Dictionary<string, object> msg, CoreWebView2Frame frame, string token)
        {
            bool ok = false;
            try
            {
                string text = GetString(msg, "text");
                if (!String.IsNullOrEmpty(text))
                {
                    Clipboard.SetText(text);
                    ok = true;
                }
            }
            catch
            {
                ok = false;
            }

            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["type"] = "copy-result";
            reply["ok"] = ok;
            reply["token"] = token;
            Reply(frame, reply);
        }

        private void DoSaveText(Dictionary<string, object> msg, CoreWebView2Frame frame, string token)
        {
            string text = GetString(msg, "text");
            string name = GetString(msg, "name");
            if (String.IsNullOrEmpty(name))
            {
                name = "提示词.txt";
            }

            string path = String.Empty;
            bool ok = false;
            try
            {
                using (SaveFileDialog dlg = new SaveFileDialog())
                {
                    dlg.Title = "保存文件";
                    dlg.FileName = Path.GetFileName(name);
                    dlg.OverwritePrompt = true;
                    dlg.AddExtension = true;
                    if (String.Equals(Path.GetExtension(name), ".json", StringComparison.OrdinalIgnoreCase))
                    {
                        dlg.Filter = "JSON 存档 (*.json)|*.json|所有文件 (*.*)|*.*";
                    }
                    else
                    {
                        dlg.Filter = "文本文件 (*.txt)|*.txt|Markdown (*.md)|*.md|所有文件 (*.*)|*.*";
                    }

                    string initial = lastSaveDir;
                    if (String.IsNullOrEmpty(initial) || !Directory.Exists(initial))
                    {
                        initial = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                    }
                    if (!String.IsNullOrEmpty(initial))
                    {
                        dlg.InitialDirectory = initial;
                    }

                    if (dlg.ShowDialog(this) == DialogResult.OK)
                    {
                        File.WriteAllText(dlg.FileName, text, new UTF8Encoding(false));
                        path = dlg.FileName;
                        lastSaveDir = Path.GetDirectoryName(path);
                        ok = true;
                    }
                }
            }
            catch (Exception ex)
            {
                LogError("DoSaveText", ex);
            }

            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["type"] = "save-result";
            reply["ok"] = ok;
            reply["path"] = path;
            reply["token"] = token;
            Reply(frame, reply);
        }

        private void DoPaste(CoreWebView2Frame frame, string token)
        {
            bool ok = false;
            string text = String.Empty;
            try
            {
                if (Clipboard.ContainsText())
                {
                    text = Clipboard.GetText();
                    ok = !String.IsNullOrEmpty(text);
                }
            }
            catch
            {
                ok = false;
            }

            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["type"] = "paste-result";
            reply["ok"] = ok;
            reply["text"] = text;
            reply["token"] = token;
            Reply(frame, reply);
        }

        private void DoOpenText(CoreWebView2Frame frame, string token)        {
            string text = String.Empty;
            string name = String.Empty;
            bool ok = false;
            try
            {
                using (OpenFileDialog dlg = new OpenFileDialog())
                {
                    dlg.Title = "打开提示词文件";
                    dlg.Filter = "文本文件 (*.txt;*.md)|*.txt;*.md|所有文件 (*.*)|*.*";
                    dlg.CheckFileExists = true;
                    if (dlg.ShowDialog(this) == DialogResult.OK)
                    {
                        text = File.ReadAllText(dlg.FileName, Encoding.UTF8);
                        name = Path.GetFileName(dlg.FileName);
                        lastSaveDir = Path.GetDirectoryName(dlg.FileName);
                        ok = true;
                    }
                }
            }
            catch (Exception ex)
            {
                LogError("DoOpenText", ex);
            }

            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["type"] = "open-result";
            reply["ok"] = ok;
            reply["text"] = text;
            reply["name"] = name;
            reply["token"] = token;
            Reply(frame, reply);
        }

        private void DoSaveImage(Dictionary<string, object> msg, CoreWebView2Frame frame, string token)
        {
            string dataUrl = GetString(msg, "dataUrl");
            string name = GetString(msg, "name");
            if (String.IsNullOrEmpty(name))
            {
                name = "色卡.png";
            }

            string path = String.Empty;
            bool ok = false;
            string error = String.Empty;
            try
            {
                int comma = dataUrl.IndexOf(',');
                if (comma <= 0)
                {
                    throw new InvalidDataException("图片数据不完整");
                }
                byte[] bytes = Convert.FromBase64String(dataUrl.Substring(comma + 1));

                using (SaveFileDialog dlg = new SaveFileDialog())
                {
                    dlg.Title = "保存色卡图片";
                    dlg.FileName = Path.GetFileName(name);
                    dlg.OverwritePrompt = true;
                    dlg.AddExtension = true;
                    dlg.Filter = "PNG 图片 (*.png)|*.png|所有文件 (*.*)|*.*";

                    string initial = lastSaveDir;
                    if (String.IsNullOrEmpty(initial) || !Directory.Exists(initial))
                    {
                        initial = Environment.GetFolderPath(Environment.SpecialFolder.MyPictures);
                    }
                    if (!String.IsNullOrEmpty(initial))
                    {
                        dlg.InitialDirectory = initial;
                    }

                    if (dlg.ShowDialog(this) == DialogResult.OK)
                    {
                        File.WriteAllBytes(dlg.FileName, bytes);
                        path = dlg.FileName;
                        lastSaveDir = Path.GetDirectoryName(path);
                        ok = true;
                    }
                }
            }
            catch (Exception ex)
            {
                error = ex.Message;
                LogError("DoSaveImage", ex);
            }

            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["type"] = "save-result";
            reply["ok"] = ok;
            reply["path"] = path;
            reply["error"] = error;
            reply["token"] = token;
            Reply(frame, reply);
        }

        private void LogError(string where, Exception ex)
        {
            try
            {
                Directory.CreateDirectory(dataDir);
                File.AppendAllText(Path.Combine(dataDir, "error.log"),
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " [" + where + "] " + ex + "\r\n\r\n");
            }
            catch
            {
            }
        }

        private int FindFreePort()
        {
            TcpListener listener = new TcpListener(IPAddress.Loopback, 0);
            try
            {
                listener.Start();
                return ((IPEndPoint)listener.LocalEndpoint).Port;
            }
            finally
            {
                listener.Stop();
            }
        }

        private static bool WaitForPing(string url, int timeoutMs)
        {
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            while (DateTime.UtcNow < deadline)
            {
                try
                {
                    HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
                    request.Proxy = null;
                    request.Timeout = 1000;
                    request.ReadWriteTimeout = 1000;
                    using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                    {
                        if ((int)response.StatusCode == 200)
                        {
                            return true;
                        }
                    }
                }
                catch
                {
                }
                Thread.Sleep(250);
            }
            return false;
        }

        private void SendToShell(Dictionary<string, object> payload)
        {
            try
            {
                if (webView.CoreWebView2 != null)
                {
                    webView.CoreWebView2.PostWebMessageAsJson(json.Serialize(payload));
                }
            }
            catch
            {
            }
        }

        private void SendAssetNestReady()
        {
            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["type"] = "assetnest-ready";
            reply["url"] = assetNestUrl;
            SendToShell(reply);
        }

        private void SendAssetNestError(string message)
        {
            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["type"] = "assetnest-error";
            reply["message"] = message;
            SendToShell(reply);
        }

        private async void StartAssetNest()
        {
            if (assetNestStarting)
            {
                return;
            }
            if (assetNestProcess != null && !assetNestProcess.HasExited && !String.IsNullOrEmpty(assetNestUrl))
            {
                SendAssetNestReady();
                return;
            }

            assetNestStarting = true;
            Dictionary<string, object> starting = new Dictionary<string, object>();
            starting["type"] = "assetnest-starting";
            SendToShell(starting);

            string exe = Path.Combine(baseDir, "vendor", "AssetNest", "AssetNest.exe");
            if (!File.Exists(exe))
            {
                assetNestStarting = false;
                SendAssetNestError("找不到素材巢程序：\r\n" + exe);
                return;
            }

            try
            {
                int port = FindFreePort();
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = exe;
                psi.Arguments = "--no-window --port " + port;
                psi.WorkingDirectory = Path.GetDirectoryName(exe);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;

                Process proc = Process.Start(psi);
                if (proc == null)
                {
                    throw new InvalidOperationException("无法创建素材巢进程");
                }
                assetNestProcess = proc;
                proc.EnableRaisingEvents = true;
                proc.Exited += OnAssetNestExited;

                string url = "http://127.0.0.1:" + port + "/";
                bool ok = await Task.Run(delegate { return WaitForPing(url + "api/ping", 30000); });

                assetNestStarting = false;
                if (ok && assetNestProcess != null && !assetNestProcess.HasExited)
                {
                    assetNestUrl = url;
                    SendAssetNestReady();
                }
                else
                {
                    StopAssetNest();
                    SendAssetNestError("素材巢启动失败或超时。\r\n请确认程序目录完整，或稍后点击“重新启动”。");
                }
            }
            catch (Exception ex)
            {
                assetNestStarting = false;
                LogError("StartAssetNest", ex);
                StopAssetNest();
                SendAssetNestError("素材巢启动失败：" + ex.Message);
            }
        }

        private void OnAssetNestExited(object sender, EventArgs e)
        {
            if (closing || IsDisposed || !IsHandleCreated)
            {
                return;
            }
            try
            {
                BeginInvoke((Action)delegate
                {
                    assetNestStarting = false;
                    assetNestUrl = null;
                    assetNestProcess = null;
                    Dictionary<string, object> reply = new Dictionary<string, object>();
                    reply["type"] = "assetnest-stopped";
                    reply["message"] = "素材巢已退出";
                    SendToShell(reply);
                });
            }
            catch
            {
            }
        }

        private void StopAssetNest()
        {
            Process proc = assetNestProcess;
            assetNestProcess = null;
            assetNestUrl = null;
            if (proc == null)
            {
                return;
            }
            try
            {
                if (!proc.HasExited)
                {
                    string taskkill = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.System),
                        "taskkill.exe");
                    ProcessStartInfo psi = new ProcessStartInfo();
                    psi.FileName = taskkill;
                    psi.Arguments = "/PID " + proc.Id + " /T /F";
                    psi.UseShellExecute = false;
                    psi.CreateNoWindow = true;
                    psi.WindowStyle = ProcessWindowStyle.Hidden;
                    Process killer = Process.Start(psi);
                    if (killer != null)
                    {
                        killer.WaitForExit(3000);
                    }
                }
            }
            catch
            {
            }
            try
            {
                proc.Dispose();
            }
            catch
            {
            }
        }

        private void OnDownloadStarting(object sender, CoreWebView2DownloadStartingEventArgs e)
        {
            try
            {
                e.Handled = true;

                string suggested = e.ResultFilePath;
                string name = String.IsNullOrEmpty(suggested)
                    ? "导出文件"
                    : Path.GetFileName(suggested);
                string ext = Path.GetExtension(name).ToLowerInvariant();

                using (SaveFileDialog dlg = new SaveFileDialog())
                {
                    dlg.Title = "保存文件";
                    dlg.FileName = name;
                    dlg.OverwritePrompt = true;
                    dlg.AddExtension = true;

                    if (ext == ".png")
                    {
                        dlg.Filter = "PNG 图片 (*.png)|*.png|所有文件 (*.*)|*.*";
                    }
                    else if (ext == ".json")
                    {
                        dlg.Filter = "JSON 存档 (*.json)|*.json|所有文件 (*.*)|*.*";
                    }
                    else
                    {
                        dlg.Filter = "文本文件 (*.txt)|*.txt|所有文件 (*.*)|*.*";
                    }

                    string initial = lastSaveDir;
                    if (String.IsNullOrEmpty(initial) || !Directory.Exists(initial))
                    {
                        initial = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                    }
                    if (!String.IsNullOrEmpty(initial))
                    {
                        dlg.InitialDirectory = initial;
                    }

                    if (dlg.ShowDialog(this) == DialogResult.OK)
                    {
                        e.ResultFilePath = dlg.FileName;
                        lastSaveDir = Path.GetDirectoryName(dlg.FileName);
                    }
                    else
                    {
                        e.Cancel = true;
                    }
                }
            }
            catch
            {
                e.Cancel = true;
            }
        }

        private void OnNewWindowRequested(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        {
            e.Handled = true;
            try
            {
                string uri = e.Uri;
                if (!String.IsNullOrEmpty(uri) &&
                    (uri.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
                     uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase)))
                {
                    Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true });
                }
            }
            catch
            {
            }
        }

        private void OnPermissionRequested(object sender, CoreWebView2PermissionRequestedEventArgs e)
        {
            try
            {
                if (e.PermissionKind == CoreWebView2PermissionKind.ClipboardRead)
                {
                    e.State = CoreWebView2PermissionState.Allow;
                }
            }
            catch
            {
            }
        }

        private void OnProcessFailed(object sender, CoreWebView2ProcessFailedEventArgs e)
        {
            try
            {
                if (e.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited)
                {
                    MessageBox.Show(this,
                        "界面进程意外退出，请重新打开程序。",
                        "AI 创作工具箱", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
            }
            catch
            {
            }
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);
            try
            {
                if (webView.CoreWebView2 == null)
                {
                    return;
                }

                if (e.KeyCode == Keys.F12)
                {
                    webView.CoreWebView2.OpenDevToolsWindow();
                    e.Handled = true;
                }
                else if (e.KeyCode == Keys.F5)
                {
                    webView.CoreWebView2.Reload();
                    e.Handled = true;
                }
                else if (e.KeyCode == Keys.D0 && e.Control)
                {
                    webView.ZoomFactor = 1.0;
                    e.Handled = true;
                }
            }
            catch
            {
            }
        }

        private void LoadWindowSettings()
        {
            try
            {
                if (!File.Exists(settingsPath))
                {
                    return;
                }

                int x = Left, y = Top, w = Width, h = Height;
                bool max = false;
                foreach (string raw in File.ReadAllLines(settingsPath, Encoding.UTF8))
                {
                    string line = raw.Trim();
                    int eq = line.IndexOf('=');
                    if (eq <= 0)
                    {
                        continue;
                    }
                    string key = line.Substring(0, eq).Trim().ToLowerInvariant();
                    string val = line.Substring(eq + 1).Trim();
                    int n;
                    if (!Int32.TryParse(val, out n))
                    {
                        continue;
                    }
                    switch (key)
                    {
                        case "x": x = n; break;
                        case "y": y = n; break;
                        case "w": if (n >= MinimumSize.Width) w = n; break;
                        case "h": if (n >= MinimumSize.Height) h = n; break;
                        case "max": max = n != 0; break;
                    }
                }

                Rectangle wa = Screen.PrimaryScreen.WorkingArea;
                Rectangle target = new Rectangle(x, y, w, h);
                bool intersects = false;
                foreach (Screen s in Screen.AllScreens)
                {
                    if (s.WorkingArea.IntersectsWith(target))
                    {
                        intersects = true;
                        break;
                    }
                }

                if (intersects)
                {
                    Bounds = target;
                }
                if (max)
                {
                    WindowState = FormWindowState.Maximized;
                }
            }
            catch
            {
            }
        }

        private void SaveWindowSettings()
        {
            try
            {
                Directory.CreateDirectory(dataDir);
                Rectangle b = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                StringBuilder sb = new StringBuilder();
                sb.AppendLine("x=" + b.X);
                sb.AppendLine("y=" + b.Y);
                sb.AppendLine("w=" + b.Width);
                sb.AppendLine("h=" + b.Height);
                sb.AppendLine("max=" + (WindowState == FormWindowState.Maximized ? "1" : "0"));
                File.WriteAllText(settingsPath, sb.ToString(), new UTF8Encoding(false));
            }
            catch
            {
            }
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            closing = true;
            SaveWindowSettings();
            StopAssetNest();
            base.OnFormClosing(e);
        }
    }
}
