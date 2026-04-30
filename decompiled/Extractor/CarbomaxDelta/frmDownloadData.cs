using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Data;
using System.Data.SQLite;
using System.Drawing;
using System.IO;
using System.Net;
using System.Windows.Forms;
using CarbomaxDelta.Data;
using CarbomaxDelta.Model;
using Newtonsoft.Json;
using Newtonsoft.Json.Converters;

namespace CarbomaxDelta;

public class frmDownloadData : Form
{
	private List<EquipamentoTO> lstEquipamentos = new List<EquipamentoTO>();

	private DataSet dsAnalise = new DataSet("Analise");

	private DataSet dsAnaliseItens = new DataSet("AnaliseItens");

	private DataRow drCurrent;

	private IContainer components;

	private TabControl tabControl1;

	private TabPage tabPage1;

	private TabPage pageDebug;

	private TextBox txtResponse2;

	private TextBox txtResponse;

	private WebBrowser browserMedicoes;

	private WebBrowser browser;

	private Button btnFechar;

	private Button btnDownload;

	private Label label3;

	private Label label2;

	private TextBox txtIP;

	private Label lblID;

	private TextBox txtEquipamentoID;

	private ComboBox cboEquipamentos;

	private TextBox txtLog;

	public frmDownloadData()
	{
		InitializeComponent();
	}

	private void frmDownloadData_Load(object sender, EventArgs e)
	{
		SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("SELECT * FROM Equipamento", sQLiteConnection);
		DataTable dataTable = new DataTable("Equipamento");
		sQLiteConnection.Open();
		dataTable.Load(sQLiteCommand.ExecuteReader());
		sQLiteConnection.Close();
		foreach (DataRow row in dataTable.Rows)
		{
			EquipamentoTO item = new EquipamentoTO(Convert.ToInt32(row["id"]), row["descricao"].ToString(), row["ip"].ToString());
			lstEquipamentos.Add(item);
		}
		cboEquipamentos.DisplayMember = "Descricao";
		cboEquipamentos.ValueMember = "EquipamentoID";
		cboEquipamentos.DataSource = lstEquipamentos;
	}

	private void btnDownload_Click(object sender, EventArgs e)
	{
		txtLog.Text = "";
		try
		{
			Logger("Starting Download of Data...");
			Cursor = Cursors.WaitCursor;
			cboEquipamentos.Enabled = false;
			btnDownload.Enabled = false;
			Uri url = new Uri("http://" + txtIP.Text + "/getallidx.cgi");
			browser.Url = url;
		}
		catch (WebException ex)
		{
			Logger("Error #1: " + ex.Message);
		}
		catch (Exception ex2)
		{
			Logger("Error #2: " + ex2.Message);
		}
		finally
		{
			Cursor = Cursors.Default;
			cboEquipamentos.Enabled = true;
			btnDownload.Enabled = true;
		}
	}

	private void Logger(string Message)
	{
		txtLog.AppendText(DateTime.Now.ToString("dd/MM/yy HH:mm:ss") + " => " + Message + "\r\n");
	}

	private void cboEquipamentos_SelectedIndexChanged(object sender, EventArgs e)
	{
		EquipamentoTO equipamentoTO = (EquipamentoTO)cboEquipamentos.SelectedItem;
		txtIP.Text = equipamentoTO.IP;
		txtEquipamentoID.Text = equipamentoTO.EquipamentoID.ToString();
	}

	private void browser_DocumentCompleted(object sender, WebBrowserDocumentCompletedEventArgs e)
	{
		try
		{
			Logger("Get ID's from Device...");
			Stream documentStream = browser.DocumentStream;
			StreamReader streamReader = new StreamReader(documentStream);
			txtResponse.Text = streamReader.ReadToEnd();
			ConverteDados();
			Logger("");
			Logger("");
			Logger("Download Completed...");
			streamReader.Close();
			documentStream.Close();
			streamReader.Dispose();
			documentStream.Dispose();
		}
		catch (Exception ex)
		{
			Logger("Error #3: " + ex.Message);
		}
	}

	private void ConverteDados()
	{
		try
		{
			txtResponse.Text = txtResponse.Text.Replace("00011900", "01011900");
			txtResponse.Text = txtResponse.Text.Replace("\\", "/");
			new DataTableConverter();
			dsAnalise = JsonConvert.DeserializeObject<DataSet>(txtResponse.Text);
			foreach (DataRow row in dsAnalise.Tables[0].Rows)
			{
				DataRow dataRow = (drCurrent = row);
				Logger("Getting Data from Index: " + dataRow["id"].ToString());
				try
				{
					Uri url = new Uri("http://" + txtIP.Text + "/getdata.cgi?btrqh=" + dataRow["id"].ToString());
					browserMedicoes.Url = url;
					while (browserMedicoes.ReadyState != WebBrowserReadyState.Complete)
					{
						Application.DoEvents();
					}
				}
				catch (Exception ex)
				{
					Logger("Error #4: " + ex.Message);
				}
			}
		}
		catch (Exception ex2)
		{
			string text = Path.GetTempPath() + "erro.log";
			StreamWriter streamWriter = new StreamWriter(text);
			streamWriter.WriteLine(DateTime.Now);
			streamWriter.WriteLine("------------------------------------------------");
			streamWriter.WriteLine(ex2.Message);
			streamWriter.WriteLine("------------------------------------------------");
			streamWriter.Write(txtResponse.Text);
			streamWriter.WriteLine("\r\n------------------------------------------------");
			streamWriter.Flush();
			streamWriter.Close();
			streamWriter.Dispose();
			MessageBox.Show(ex2.Message + "\r\n\r\n Log File: " + text);
		}
	}

	private void ConverteDadosMedicoes()
	{
		try
		{
			txtResponse.Text = txtResponse.Text.Replace("00011900", "01011900");
			txtResponse.Text = txtResponse.Text.Replace("\\", "/");
			new DataTableConverter();
			dsAnaliseItens = JsonConvert.DeserializeObject<DataSet>(txtResponse2.Text);
			Logger("Data Received, saving..");
			EquipamentoTO equipamentoTO = (EquipamentoTO)cboEquipamentos.SelectedItem;
			DbUtils.Erro = "";
			DbUtils.GravaDados(equipamentoTO.EquipamentoID, equipamentoTO.IP, drCurrent, dsAnaliseItens.Tables[0]);
			if (DbUtils.Erro != "")
			{
				MessageBox.Show(DbUtils.Erro);
			}
			Logger("Data Saved...");
		}
		catch (Exception ex)
		{
			Logger("Error #5: " + ex.Message);
		}
	}

	private void browserMedicoes_DocumentCompleted(object sender, WebBrowserDocumentCompletedEventArgs e)
	{
		try
		{
			Stream documentStream = browserMedicoes.DocumentStream;
			StreamReader streamReader = new StreamReader(documentStream);
			txtResponse2.Text = streamReader.ReadToEnd();
			ConverteDadosMedicoes();
			streamReader.Close();
			documentStream.Close();
			streamReader.Dispose();
			documentStream.Dispose();
		}
		catch (Exception ex)
		{
			MessageBox.Show(ex.Message);
		}
	}

	private void btnFechar_Click(object sender, EventArgs e)
	{
		Close();
	}

	private void tabControl1_Selecting(object sender, TabControlCancelEventArgs e)
	{
		if (e.TabPage == pageDebug)
		{
			e.Cancel = true;
		}
	}

	protected override void Dispose(bool disposing)
	{
		if (disposing && components != null)
		{
			components.Dispose();
		}
		base.Dispose(disposing);
	}

	private void InitializeComponent()
	{
		System.ComponentModel.ComponentResourceManager componentResourceManager = new System.ComponentModel.ComponentResourceManager(typeof(CarbomaxDelta.frmDownloadData));
		this.tabControl1 = new System.Windows.Forms.TabControl();
		this.tabPage1 = new System.Windows.Forms.TabPage();
		this.txtLog = new System.Windows.Forms.TextBox();
		this.pageDebug = new System.Windows.Forms.TabPage();
		this.txtResponse2 = new System.Windows.Forms.TextBox();
		this.txtResponse = new System.Windows.Forms.TextBox();
		this.browserMedicoes = new System.Windows.Forms.WebBrowser();
		this.browser = new System.Windows.Forms.WebBrowser();
		this.btnFechar = new System.Windows.Forms.Button();
		this.btnDownload = new System.Windows.Forms.Button();
		this.label3 = new System.Windows.Forms.Label();
		this.label2 = new System.Windows.Forms.Label();
		this.txtIP = new System.Windows.Forms.TextBox();
		this.lblID = new System.Windows.Forms.Label();
		this.txtEquipamentoID = new System.Windows.Forms.TextBox();
		this.cboEquipamentos = new System.Windows.Forms.ComboBox();
		this.tabControl1.SuspendLayout();
		this.tabPage1.SuspendLayout();
		this.pageDebug.SuspendLayout();
		base.SuspendLayout();
		componentResourceManager.ApplyResources(this.tabControl1, "tabControl1");
		this.tabControl1.Controls.Add(this.tabPage1);
		this.tabControl1.Controls.Add(this.pageDebug);
		this.tabControl1.Name = "tabControl1";
		this.tabControl1.SelectedIndex = 0;
		this.tabControl1.Selecting += new System.Windows.Forms.TabControlCancelEventHandler(tabControl1_Selecting);
		componentResourceManager.ApplyResources(this.tabPage1, "tabPage1");
		this.tabPage1.Controls.Add(this.txtLog);
		this.tabPage1.Name = "tabPage1";
		this.tabPage1.UseVisualStyleBackColor = true;
		componentResourceManager.ApplyResources(this.txtLog, "txtLog");
		this.txtLog.BackColor = System.Drawing.Color.White;
		this.txtLog.Name = "txtLog";
		this.txtLog.ReadOnly = true;
		componentResourceManager.ApplyResources(this.pageDebug, "pageDebug");
		this.pageDebug.Controls.Add(this.txtResponse2);
		this.pageDebug.Controls.Add(this.txtResponse);
		this.pageDebug.Controls.Add(this.browserMedicoes);
		this.pageDebug.Controls.Add(this.browser);
		this.pageDebug.Name = "pageDebug";
		this.pageDebug.UseVisualStyleBackColor = true;
		componentResourceManager.ApplyResources(this.txtResponse2, "txtResponse2");
		this.txtResponse2.Name = "txtResponse2";
		componentResourceManager.ApplyResources(this.txtResponse, "txtResponse");
		this.txtResponse.Name = "txtResponse";
		componentResourceManager.ApplyResources(this.browserMedicoes, "browserMedicoes");
		this.browserMedicoes.Name = "browserMedicoes";
		this.browserMedicoes.DocumentCompleted += new System.Windows.Forms.WebBrowserDocumentCompletedEventHandler(browserMedicoes_DocumentCompleted);
		componentResourceManager.ApplyResources(this.browser, "browser");
		this.browser.IsWebBrowserContextMenuEnabled = false;
		this.browser.Name = "browser";
		this.browser.WebBrowserShortcutsEnabled = false;
		this.browser.DocumentCompleted += new System.Windows.Forms.WebBrowserDocumentCompletedEventHandler(browser_DocumentCompleted);
		componentResourceManager.ApplyResources(this.btnFechar, "btnFechar");
		this.btnFechar.Name = "btnFechar";
		this.btnFechar.UseVisualStyleBackColor = true;
		this.btnFechar.Click += new System.EventHandler(btnFechar_Click);
		componentResourceManager.ApplyResources(this.btnDownload, "btnDownload");
		this.btnDownload.Name = "btnDownload";
		this.btnDownload.UseVisualStyleBackColor = true;
		this.btnDownload.Click += new System.EventHandler(btnDownload_Click);
		componentResourceManager.ApplyResources(this.label3, "label3");
		this.label3.Name = "label3";
		componentResourceManager.ApplyResources(this.label2, "label2");
		this.label2.Name = "label2";
		componentResourceManager.ApplyResources(this.txtIP, "txtIP");
		this.txtIP.Name = "txtIP";
		this.txtIP.ReadOnly = true;
		componentResourceManager.ApplyResources(this.lblID, "lblID");
		this.lblID.Name = "lblID";
		componentResourceManager.ApplyResources(this.txtEquipamentoID, "txtEquipamentoID");
		this.txtEquipamentoID.Name = "txtEquipamentoID";
		this.txtEquipamentoID.ReadOnly = true;
		componentResourceManager.ApplyResources(this.cboEquipamentos, "cboEquipamentos");
		this.cboEquipamentos.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList;
		this.cboEquipamentos.FormattingEnabled = true;
		this.cboEquipamentos.Name = "cboEquipamentos";
		this.cboEquipamentos.SelectedIndexChanged += new System.EventHandler(cboEquipamentos_SelectedIndexChanged);
		componentResourceManager.ApplyResources(this, "$this");
		base.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
		base.Controls.Add(this.label3);
		base.Controls.Add(this.label2);
		base.Controls.Add(this.txtIP);
		base.Controls.Add(this.lblID);
		base.Controls.Add(this.txtEquipamentoID);
		base.Controls.Add(this.cboEquipamentos);
		base.Controls.Add(this.btnDownload);
		base.Controls.Add(this.btnFechar);
		base.Controls.Add(this.tabControl1);
		base.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog;
		base.MaximizeBox = false;
		base.MinimizeBox = false;
		base.Name = "frmDownloadData";
		base.ShowIcon = false;
		base.Load += new System.EventHandler(frmDownloadData_Load);
		this.tabControl1.ResumeLayout(false);
		this.tabPage1.ResumeLayout(false);
		this.tabPage1.PerformLayout();
		this.pageDebug.ResumeLayout(false);
		this.pageDebug.PerformLayout();
		base.ResumeLayout(false);
		base.PerformLayout();
	}
}
