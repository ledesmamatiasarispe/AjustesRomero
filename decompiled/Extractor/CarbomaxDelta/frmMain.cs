using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Configuration;
using System.Data;
using System.Data.SQLite;
using System.Drawing;
using System.Globalization;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using System.Windows.Forms.DataVisualization.Charting;
using CarbomaxDelta.Data;
using CarbomaxDelta.Model;
using CarbomaxDelta.Properties;

namespace CarbomaxDelta;

public class frmMain : Form
{
	private List<EquipamentoTO> lstEquipamentos = new List<EquipamentoTO>();

	private List<EquipamentoTO> lstEquipamentos2 = new List<EquipamentoTO>();

	private DataTable tblAnalise = new DataTable("Analise");

	private DataTable tblAnaliseData = new DataTable("AnaliseData");

	private DataGridViewCellStyle style2 = new DataGridViewCellStyle();

	private DataGridViewCellStyle style1 = new DataGridViewCellStyle();

	private int defLanguage;

	private int defUnity;

	private string un = "";

	private IContainer components;

	private TabControl tab;

	private TabPage tabAnalise;

	private MenuStrip menuStrip1;

	private ToolStripMenuItem arquivoToolStripMenuItem;

	private ToolStripMenuItem equipamentosToolStripMenuItem;

	private ToolStripSeparator toolStripSeparator1;

	private ToolStripMenuItem downloadDeDadosToolStripMenuItem;

	private ToolStripSeparator toolStripSeparator2;

	private ToolStripMenuItem sairToolStripMenuItem;

	private DateTimePicker txtDtInicio;

	private DateTimePicker txtDtTermino;

	private ComboBox cboEquipamentoIni;

	private TabPage tabDados;

	private TabPage tabGrafico;

	private Chart chtTempDeriv;

	private Label lblPeriodo;

	private Label lblEquip;

	private PictureBox pictureBox1;

	private PictureBox pictureBox2;

	private DataGridView grdAnalise;

	private Label lblUnid;

	private ComboBox cboUN;

	private DataGridView grdData;

	private SaveFileDialog saveFileDialog1;

	private PictureBox pictureBox7;

	private ComboBox cboModo;

	private Label lblModo;

	private ToolStripMenuItem mniDeleteAllData;

	private Button btnGerar;

	private ToolStrip toolStrip1;

	private ToolStripButton btTools;

	private ToolStripButton btDown;

	private ToolStripButton btPor;

	private ToolStripButton btEng;

	private ToolStripButton btExit;

	private ToolStripSeparator toolStripSeparator3;

	private ToolStripButton btAbout;

	private ToolStripSeparator toolStripSeparator4;

	private ToolStripMenuItem mniTabelaDados;

	private BindingSource analiseDataBindingSource;

	private DataGridViewImageColumn dataGridViewImageColumn1;

	private DataGridViewImageColumn dataGridViewImageColumn2;

	private ToolStripSeparator toolStripSeparator5;

	private ToolStripSeparator toolStripSeparator6;

	private ToolStripButton btReport;

	private ToolStripSeparator toolStripSeparator7;

	private ToolStripSeparator toolStripSeparator8;

	private DataGridViewImageColumn colPDF;

	private DataGridViewImageColumn colXLS;

	public string AssemblyVersion => Assembly.GetExecutingAssembly().GetName().Version.ToString();

	public string AssemblyProduct
	{
		get
		{
			object[] customAttributes = Assembly.GetExecutingAssembly().GetCustomAttributes(typeof(AssemblyProductAttribute), inherit: false);
			if (customAttributes.Length == 0)
			{
				return "";
			}
			return ((AssemblyProductAttribute)customAttributes[0]).Product;
		}
	}

	public frmMain()
	{
		InitializeComponent();
		style2.Format = "#,##0.00";
		style1.Format = "#,##0.0";
	}

	private void frmMain_Load(object sender, EventArgs e)
	{
		Text = AssemblyProduct + " - " + $"{AssemblyVersion}";
		Configuration configuration = ConfigurationManager.OpenExeConfiguration(ConfigurationUserLevel.None);
		if (ConfigurationManager.AppSettings["Language"] == null)
		{
			configuration.AppSettings.Settings.Add("Language", "0");
			configuration.Save(ConfigurationSaveMode.Minimal);
			defLanguage = 0;
		}
		else
		{
			defLanguage = Convert.ToInt16(configuration.AppSettings.Settings["Language"].Value);
		}
		if (ConfigurationManager.AppSettings["Unity"] == null)
		{
			configuration.AppSettings.Settings.Add("Unity", "0");
			configuration.Save(ConfigurationSaveMode.Minimal);
			defUnity = 0;
		}
		else
		{
			defUnity = Convert.ToInt16(configuration.AppSettings.Settings["Unity"].Value);
		}
		if (defLanguage == 0)
		{
			trocarIdioma("pt-BR");
		}
		else
		{
			trocarIdioma("en-US");
		}
		btEng.Enabled = defLanguage == 0;
		btPor.Enabled = defLanguage == 1;
		cboUN.SelectedIndex = defUnity;
		un = ((defUnity == 1) ? "°F" : "°C");
		Inicializa();
		base.WindowState = FormWindowState.Maximized;
	}

	private void Inicializa()
	{
		try
		{
			cboModo.SelectedIndex = 0;
			CarregaEquipamentos();
			base.WindowState = FormWindowState.Maximized;
			txtDtTermino.Value = DateTime.Now.AddDays(5.0);
			if (defLanguage == 1)
			{
				txtDtInicio.CustomFormat = "MM/dd/yyyy";
				txtDtTermino.CustomFormat = "MM/dd/yyyy";
				chtTempDeriv.ChartAreas[0].Axes[1].Title = "Temperature " + un;
				chtTempDeriv.ChartAreas[0].Axes[3].Title = "Derivative " + un + " / sec";
			}
			else
			{
				txtDtInicio.CustomFormat = "dd/MM/yyyy";
				txtDtTermino.CustomFormat = "dd/MM/yyyy";
				chtTempDeriv.ChartAreas[0].Axes[1].Title = "Temperatura " + un;
				chtTempDeriv.ChartAreas[0].Axes[3].Title = "Derivada " + un + " / seg";
			}
			txtDtInicio.Refresh();
			txtDtTermino.Refresh();
		}
		catch (Exception ex)
		{
			MessageBox.Show(ex.Message);
		}
	}

	private void CarregaEquipamentos()
	{
		SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("SELECT * FROM Equipamento", sQLiteConnection);
		DataTable dataTable = new DataTable("Equipamento");
		sQLiteConnection.Open();
		dataTable.Load(sQLiteCommand.ExecuteReader());
		sQLiteConnection.Close();
		lstEquipamentos.Clear();
		if (defLanguage == 0)
		{
			EquipamentoTO item = new EquipamentoTO(0, "Todos", "0.0.0.0");
			lstEquipamentos.Add(item);
		}
		else
		{
			EquipamentoTO item2 = new EquipamentoTO(0, "All", "0.0.0.0");
			lstEquipamentos.Add(item2);
		}
		foreach (DataRow row in dataTable.Rows)
		{
			EquipamentoTO item3 = new EquipamentoTO(Convert.ToInt32(row["id"]), row["Descricao"].ToString(), row["IP"].ToString());
			lstEquipamentos.Add(item3);
		}
		cboEquipamentoIni.DataSource = null;
		cboEquipamentoIni.DisplayMember = "Descricao";
		cboEquipamentoIni.ValueMember = "EquipamentoID";
		cboEquipamentoIni.DataSource = lstEquipamentos;
		cboEquipamentoIni.Refresh();
	}

	private void trocarIdioma(string idioma)
	{
		base.WindowState = FormWindowState.Normal;
		Thread.CurrentThread.CurrentCulture = new CultureInfo(idioma);
		Thread.CurrentThread.CurrentUICulture = new CultureInfo(idioma);
		base.Controls.Clear();
		InitializeComponent();
		cboUN.SelectedIndex = defUnity;
		Inicializa();
	}

	private void cboEquipamentoIni_SelectedIndexChanged(object sender, EventArgs e)
	{
		if (cboEquipamentoIni.SelectedIndex != -1)
		{
			btnGerar_Click(sender, e);
		}
	}

	private void btnGerar_Click(object sender, EventArgs e)
	{
		btnGerar.Enabled = false;
		Cursor = Cursors.WaitCursor;
		string text = "yyyy-MM-dd";
		try
		{
			chtTempDeriv.ChartAreas[0].Axes[3].Minimum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, -6.0);
			chtTempDeriv.ChartAreas[0].Axes[3].Maximum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, 6.0);
			if (cboModo.SelectedIndex == 3)
			{
				chtTempDeriv.ChartAreas[0].Axes[2].Minimum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, 400.0);
				chtTempDeriv.ChartAreas[0].Axes[2].Maximum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, 800.0);
			}
			else
			{
				chtTempDeriv.ChartAreas[0].Axes[2].Minimum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, 900.0);
				chtTempDeriv.ChartAreas[0].Axes[2].Maximum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, 1400.0);
			}
			grdAnalise.DataSource = null;
			grdAnalise.Rows.Clear();
			grdAnalise.Refresh();
			atualizaTabDetalhe();
			tab.SelectedTab = tabAnalise;
			btReport.Enabled = true;
			SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
			SQLiteCommand sQLiteCommand = new SQLiteCommand("", sQLiteConnection);
			sQLiteCommand.Parameters.AddWithValue("@DtIni", txtDtInicio.Value.ToString(text));
			sQLiteCommand.Parameters.AddWithValue("@DtFim", txtDtTermino.Value.AddDays(1.0).ToString(text));
			if (cboEquipamentoIni.SelectedIndex > 0)
			{
				sQLiteCommand.Parameters.AddWithValue("@IDEquip", ((EquipamentoTO)cboEquipamentoIni.SelectedItem).EquipamentoID);
			}
			else
			{
				sQLiteCommand.Parameters.AddWithValue("@IDEquip", "%");
			}
			if (cboModo.SelectedIndex == 0)
			{
				sQLiteCommand.CommandText = "SELECT DISTINCT Analise.id, '" + un + "' AS Unidade, Analise.ip, Descricao, Modo, Canal, Material, Lote, Observacao, DtInicio, DtTermino, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, tag1, tag2, tag3, tag4, modelo FROM Analise INNER JOIN Equipamento ON Equipamento.id = Analise.id_equipamento WHERE DhLeitura >= @DtIni AND DhLeitura < @DtFim AND Analise.id_equipamento LIKE @IDEquip AND Analise.Modo LIKE '%CARB%' AND Analise.Modelo = '0'";
			}
			else if (cboModo.SelectedIndex == 1)
			{
				sQLiteCommand.CommandText = "SELECT DISTINCT Analise.id, '" + un + "' AS Unidade, Analise.ip, Descricao, Modo, Canal, Material, Lote, Observacao, DtInicio, DtTermino, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, tag1, tag2, tag3, tag4, modelo FROM Analise INNER JOIN Equipamento ON Equipamento.id = Analise.id_equipamento WHERE DhLeitura >= @DtIni AND DhLeitura < @DtFim AND Analise.id_equipamento LIKE @IDEquip AND Analise.Modo LIKE 'MICRO%' AND Analise.Modelo = '0'";
			}
			else if (cboModo.SelectedIndex == 2)
			{
				sQLiteCommand.CommandText = "SELECT DISTINCT Analise.id, '" + un + "' AS Unidade, Analise.ip, Descricao, Modo, Canal, Material, Lote, Observacao, DtInicio, DtTermino, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, tag1, tag2, tag3, tag4, modelo FROM Analise INNER JOIN Equipamento ON Equipamento.id = Analise.id_equipamento WHERE DhLeitura >= @DtIni AND DhLeitura < @DtFim AND Analise.id_equipamento LIKE @IDEquip AND Analise.Modo LIKE 'MICRO%' AND Analise.Modelo = '1'";
			}
			else if (cboModo.SelectedIndex == 3)
			{
				sQLiteCommand.CommandText = "SELECT DISTINCT Analise.id, '" + un + "' AS Unidade, Analise.ip, Descricao, Modo, Canal, Material, Lote, Observacao, DtInicio, DtTermino, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, tag1, tag2, tag3, tag4, modelo FROM Analise INNER JOIN Equipamento ON Equipamento.id = Analise.id_equipamento WHERE DhLeitura >= @DtIni AND DhLeitura < @DtFim AND Analise.id_equipamento LIKE @IDEquip AND Analise.Modelo = '2' AND (Analise.Modo LIKE 'COPO%' OR Analise.Modo LIKE 'SONDA%')";
			}
			else
			{
				sQLiteCommand.CommandText = "SELECT DISTINCT Analise.id, '" + un + "' AS Unidade, Analise.ip, Descricao, Modo, Canal, Material, Lote, Observacao, DtInicio, DtTermino, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, tag1, tag2, tag3, tag4, modelo FROM Analise INNER JOIN Equipamento ON Equipamento.id = Analise.id_equipamento WHERE DhLeitura >= @DtIni AND DhLeitura < @DtFim AND Analise.id_equipamento LIKE @IDEquip AND Analise.Modo LIKE 'LAN%'";
			}
			tblAnalise = new DataTable("Analise");
			sQLiteConnection.Open();
			tblAnalise.Load(sQLiteCommand.ExecuteReader());
			sQLiteConnection.Close();
			foreach (DataRow row in tblAnalise.Rows)
			{
				if (cboModo.SelectedIndex == 0)
				{
					row.BeginEdit();
					row["c1"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c1"]));
					row["c2"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c2"]));
					row["c4"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c4"]));
					row["c7"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c7"]));
					row["c8"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c8"]));
					row.EndEdit();
				}
				else if (cboModo.SelectedIndex == 1 || cboModo.SelectedIndex == 2)
				{
					row.BeginEdit();
					row["c1"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c1"]));
					row["c2"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c2"]));
					row["c4"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c4"]));
					row["c5"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c5"]));
					row["c6"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c6"]));
					row["c7"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c7"]));
					row["c8"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c8"]));
					row.EndEdit();
				}
				else if (cboModo.SelectedIndex == 3)
				{
					row.BeginEdit();
					row["c1"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c1"]));
					row["c2"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c2"]));
					row["c3"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c3"]));
					row["c5"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c5"]));
					row["c6"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c6"]));
					row["c7"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c7"]));
					row.EndEdit();
				}
				else
				{
					row.BeginEdit();
					row["c1"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c1"]));
					row["c2"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c2"]));
					row["c3"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["c3"]));
					row.EndEdit();
				}
				if (defLanguage == 1)
				{
					row.BeginEdit();
					if (row["Modo"].ToString().Contains("CARB"))
					{
						row["Modo"] = "CARBON";
					}
					else if (row["Modo"].ToString().Contains("MICRO"))
					{
						row["Modo"] = "MICROSTRUCTURE";
					}
					else if (row["Modo"].ToString().Contains("COP"))
					{
						row["Modo"] = "CUP";
					}
					else if (row["Modo"].ToString().Contains("SOND"))
					{
						row["Modo"] = "PROBE";
					}
					else
					{
						row["Modo"] = "LANCE";
					}
					row.EndEdit();
				}
			}
			grdAnalise.DataSource = tblAnalise;
			grdAnalise.Columns[3].Visible = false;
			grdAnalise.Columns["modelo"].Visible = false;
			for (int i = 0; i < grdAnalise.ColumnCount; i++)
			{
				if (grdAnalise.Columns[i].Name.StartsWith("c"))
				{
					grdAnalise.Columns[i].DefaultCellStyle = style2;
				}
				if (defLanguage == 0)
				{
					if (grdAnalise.Columns[i].Name == "descricao")
					{
						grdAnalise.Columns[i].HeaderText = "Equipamento";
					}
					else if (grdAnalise.Columns[i].Name == "ip")
					{
						grdAnalise.Columns[i].HeaderText = "IP";
					}
					else if (grdAnalise.Columns[i].Name == "id")
					{
						grdAnalise.Columns[i].HeaderText = "ID";
					}
					else if (grdAnalise.Columns[i].Name == "Modo")
					{
						grdAnalise.Columns[i].HeaderText = "Modo";
					}
					else if (grdAnalise.Columns[i].Name == "Lote")
					{
						grdAnalise.Columns[i].HeaderText = "Lote";
					}
					else if (grdAnalise.Columns[i].Name == "Canal")
					{
						grdAnalise.Columns[i].HeaderText = "Canal";
					}
					else if (grdAnalise.Columns[i].Name == "DtInicio")
					{
						grdAnalise.Columns[i].DefaultCellStyle.Format = "dd/MM/yyyy HH:mm:ss";
						grdAnalise.Columns[i].HeaderText = "Dt Início";
					}
					else if (grdAnalise.Columns[i].Name == "DtTermino")
					{
						grdAnalise.Columns[i].DefaultCellStyle.Format = "dd/MM/yyyy HH:mm:ss";
						grdAnalise.Columns[i].HeaderText = "Dt Término";
					}
					else if (grdAnalise.Columns[i].Name == "Observacao")
					{
						grdAnalise.Columns[i].HeaderText = "Observação";
					}
					if (cboModo.SelectedIndex == 0)
					{
						if (grdAnalise.Columns[i].Name == "c1")
						{
							grdAnalise.Columns[i].HeaderText = "Pico";
						}
						else if (grdAnalise.Columns[i].Name == "c2")
						{
							grdAnalise.Columns[i].HeaderText = "TL";
						}
						else if (grdAnalise.Columns[i].Name == "c3")
						{
							grdAnalise.Columns[i].HeaderText = "CE %";
						}
						else if (grdAnalise.Columns[i].Name == "c4")
						{
							grdAnalise.Columns[i].HeaderText = "TS";
						}
						else if (grdAnalise.Columns[i].Name == "c5")
						{
							grdAnalise.Columns[i].HeaderText = "C %";
						}
						else if (grdAnalise.Columns[i].Name == "c6")
						{
							grdAnalise.Columns[i].HeaderText = "Si %";
						}
						else if (grdAnalise.Columns[i].Name == "c7")
						{
							grdAnalise.Columns[i].HeaderText = "TF";
						}
						else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10,tag".Contains(grdAnalise.Columns[i].Name))
						{
							grdAnalise.Columns[i].Visible = false;
						}
					}
					else if (cboModo.SelectedIndex == 1)
					{
						if (grdAnalise.Columns[i].Name == "c1")
						{
							grdAnalise.Columns[i].HeaderText = "Pico";
						}
						else if (grdAnalise.Columns[i].Name == "c2")
						{
							grdAnalise.Columns[i].HeaderText = "TL";
						}
						else if (grdAnalise.Columns[i].Name == "c3")
						{
							grdAnalise.Columns[i].HeaderText = "CE %";
						}
						else if (grdAnalise.Columns[i].Name == "c4")
						{
							grdAnalise.Columns[i].HeaderText = "TSE";
						}
						else if (grdAnalise.Columns[i].Name == "c5")
						{
							grdAnalise.Columns[i].HeaderText = "TRE";
						}
						else if (grdAnalise.Columns[i].Name == "c6")
						{
							grdAnalise.Columns[i].HeaderText = "REC";
						}
						else if (grdAnalise.Columns[i].Name == "c7")
						{
							grdAnalise.Columns[i].HeaderText = "∆ REC " + un + "/s";
						}
						else if (grdAnalise.Columns[i].Name == "c8")
						{
							grdAnalise.Columns[i].HeaderText = "TF";
						}
						else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10".Contains(grdAnalise.Columns[i].Name))
						{
							grdAnalise.Columns[i].Visible = false;
						}
					}
					else if (cboModo.SelectedIndex == 2)
					{
						if (grdAnalise.Columns[i].Name == "c1")
						{
							grdAnalise.Columns[i].HeaderText = "Pico";
						}
						else if (grdAnalise.Columns[i].Name == "c2")
						{
							grdAnalise.Columns[i].HeaderText = "TL";
						}
						else if (grdAnalise.Columns[i].Name == "c3")
						{
							grdAnalise.Columns[i].HeaderText = "CE %";
						}
						else if (grdAnalise.Columns[i].Name == "c4")
						{
							grdAnalise.Columns[i].HeaderText = "Eutetic";
						}
						else if (grdAnalise.Columns[i].Name == "c5")
						{
							grdAnalise.Columns[i].HeaderText = "RecEut";
						}
						else if (grdAnalise.Columns[i].Name == "c6")
						{
							grdAnalise.Columns[i].HeaderText = "REC";
						}
						else if (grdAnalise.Columns[i].Name == "c7")
						{
							grdAnalise.Columns[i].HeaderText = "∆ REC " + un + "/s";
						}
						else if (grdAnalise.Columns[i].Name == "c8")
						{
							grdAnalise.Columns[i].HeaderText = "Solid";
						}
						else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10".Contains(grdAnalise.Columns[i].Name))
						{
							grdAnalise.Columns[i].Visible = false;
						}
					}
					else if (cboModo.SelectedIndex == 3)
					{
						if (grdAnalise.Columns[i].Name == "c1")
						{
							grdAnalise.Columns[i].HeaderText = "Pico";
						}
						else if (grdAnalise.Columns[i].Name == "c2")
						{
							grdAnalise.Columns[i].HeaderText = "TNL";
						}
						else if (grdAnalise.Columns[i].Name == "c3")
						{
							grdAnalise.Columns[i].HeaderText = "RecL";
						}
						else if (grdAnalise.Columns[i].Name == "c4")
						{
							grdAnalise.Columns[i].HeaderText = "TLiq";
						}
						else if (grdAnalise.Columns[i].Name == "c5")
						{
							grdAnalise.Columns[i].HeaderText = "TEM";
						}
						else if (grdAnalise.Columns[i].Name == "c6")
						{
							grdAnalise.Columns[i].HeaderText = "TER";
						}
						else if (grdAnalise.Columns[i].Name == "c7")
						{
							grdAnalise.Columns[i].HeaderText = "RecE";
						}
						else if (grdAnalise.Columns[i].Name == "c8")
						{
							grdAnalise.Columns[i].HeaderText = "TRE";
						}
						else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10".Contains(grdAnalise.Columns[i].Name))
						{
							grdAnalise.Columns[i].Visible = false;
						}
					}
					else if (grdAnalise.Columns[i].Name == "c1")
					{
						grdAnalise.Columns[i].HeaderText = "Temperatura";
					}
					else if (grdAnalise.Columns[i].Name == "c2")
					{
						grdAnalise.Columns[i].HeaderText = "Tol.Min";
					}
					else if (grdAnalise.Columns[i].Name == "c3")
					{
						grdAnalise.Columns[i].HeaderText = "Tol.Max";
					}
					else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10,tag".Contains(grdAnalise.Columns[i].Name))
					{
						grdAnalise.Columns[i].Visible = false;
					}
					continue;
				}
				if (grdAnalise.Columns[i].Name == "descricao")
				{
					grdAnalise.Columns[i].HeaderText = "Device";
				}
				else if (grdAnalise.Columns[i].Name == "ip")
				{
					grdAnalise.Columns[i].HeaderText = "IP";
				}
				else if (grdAnalise.Columns[i].Name == "id")
				{
					grdAnalise.Columns[i].HeaderText = "ID";
				}
				else if (grdAnalise.Columns[i].Name == "Modo")
				{
					grdAnalise.Columns[i].HeaderText = "Mode";
				}
				else if (grdAnalise.Columns[i].Name == "Lote")
				{
					grdAnalise.Columns[i].HeaderText = "Lot";
				}
				else if (grdAnalise.Columns[i].Name == "Canal")
				{
					grdAnalise.Columns[i].HeaderText = "Channel";
				}
				else if (grdAnalise.Columns[i].Name == "DtInicio")
				{
					grdAnalise.Columns[i].DefaultCellStyle.Format = "MM/dd/yyyy HH:mm:ss";
					grdAnalise.Columns[i].HeaderText = "Start Date";
				}
				else if (grdAnalise.Columns[i].Name == "DtTermino")
				{
					grdAnalise.Columns[i].DefaultCellStyle.Format = "MM/dd/yyyy HH:mm:ss";
					grdAnalise.Columns[i].HeaderText = "Stop Date";
				}
				else if (grdAnalise.Columns[i].Name == "Observacao")
				{
					grdAnalise.Columns[i].HeaderText = "Observation";
				}
				if (cboModo.SelectedIndex == 0)
				{
					if (grdAnalise.Columns[i].Name == "c1")
					{
						grdAnalise.Columns[i].HeaderText = "Peak";
					}
					else if (grdAnalise.Columns[i].Name == "c2")
					{
						grdAnalise.Columns[i].HeaderText = "TL";
					}
					else if (grdAnalise.Columns[i].Name == "c3")
					{
						grdAnalise.Columns[i].HeaderText = "CE %";
					}
					else if (grdAnalise.Columns[i].Name == "c4")
					{
						grdAnalise.Columns[i].HeaderText = "TS";
					}
					else if (grdAnalise.Columns[i].Name == "c5")
					{
						grdAnalise.Columns[i].HeaderText = "C %";
					}
					else if (grdAnalise.Columns[i].Name == "c6")
					{
						grdAnalise.Columns[i].HeaderText = "Si %";
					}
					else if (grdAnalise.Columns[i].Name == "c7")
					{
						grdAnalise.Columns[i].HeaderText = "EF";
					}
					else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10,tag".Contains(grdAnalise.Columns[i].Name))
					{
						grdAnalise.Columns[i].Visible = false;
					}
				}
				else if (cboModo.SelectedIndex == 1)
				{
					if (grdAnalise.Columns[i].Name == "c1")
					{
						grdAnalise.Columns[i].HeaderText = "Peak";
					}
					else if (grdAnalise.Columns[i].Name == "c2")
					{
						grdAnalise.Columns[i].HeaderText = "TL";
					}
					else if (grdAnalise.Columns[i].Name == "c3")
					{
						grdAnalise.Columns[i].HeaderText = "CE %";
					}
					else if (grdAnalise.Columns[i].Name == "c4")
					{
						grdAnalise.Columns[i].HeaderText = "TEU";
					}
					else if (grdAnalise.Columns[i].Name == "c5")
					{
						grdAnalise.Columns[i].HeaderText = "TER";
					}
					else if (grdAnalise.Columns[i].Name == "c6")
					{
						grdAnalise.Columns[i].HeaderText = "REC";
					}
					else if (grdAnalise.Columns[i].Name == "c7")
					{
						grdAnalise.Columns[i].HeaderText = "∆ REC " + un + "/s";
					}
					else if (grdAnalise.Columns[i].Name == "c8")
					{
						grdAnalise.Columns[i].HeaderText = "EF";
					}
					else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10".Contains(grdAnalise.Columns[i].Name))
					{
						grdAnalise.Columns[i].Visible = false;
					}
				}
				else if (cboModo.SelectedIndex == 2)
				{
					if (grdAnalise.Columns[i].Name == "c1")
					{
						grdAnalise.Columns[i].HeaderText = "Peak";
					}
					else if (grdAnalise.Columns[i].Name == "c2")
					{
						grdAnalise.Columns[i].HeaderText = "TL";
					}
					else if (grdAnalise.Columns[i].Name == "c3")
					{
						grdAnalise.Columns[i].HeaderText = "CE %";
					}
					else if (grdAnalise.Columns[i].Name == "c4")
					{
						grdAnalise.Columns[i].HeaderText = "Eutetic";
					}
					else if (grdAnalise.Columns[i].Name == "c5")
					{
						grdAnalise.Columns[i].HeaderText = "RecEut";
					}
					else if (grdAnalise.Columns[i].Name == "c6")
					{
						grdAnalise.Columns[i].HeaderText = "REC";
					}
					else if (grdAnalise.Columns[i].Name == "c7")
					{
						grdAnalise.Columns[i].HeaderText = "∆ REC " + un + "/s";
					}
					else if (grdAnalise.Columns[i].Name == "c8")
					{
						grdAnalise.Columns[i].HeaderText = "Solid";
					}
					else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10".Contains(grdAnalise.Columns[i].Name))
					{
						grdAnalise.Columns[i].Visible = false;
					}
				}
				else if (cboModo.SelectedIndex == 3)
				{
					if (grdAnalise.Columns[i].Name == "c1")
					{
						grdAnalise.Columns[i].HeaderText = "Peak";
					}
					else if (grdAnalise.Columns[i].Name == "c2")
					{
						grdAnalise.Columns[i].HeaderText = "TNL";
					}
					else if (grdAnalise.Columns[i].Name == "c3")
					{
						grdAnalise.Columns[i].HeaderText = "LRec";
					}
					else if (grdAnalise.Columns[i].Name == "c4")
					{
						grdAnalise.Columns[i].HeaderText = "LRT";
					}
					else if (grdAnalise.Columns[i].Name == "c5")
					{
						grdAnalise.Columns[i].HeaderText = "TEU";
					}
					else if (grdAnalise.Columns[i].Name == "c6")
					{
						grdAnalise.Columns[i].HeaderText = "TER";
					}
					else if (grdAnalise.Columns[i].Name == "c7")
					{
						grdAnalise.Columns[i].HeaderText = "EutR";
					}
					else if (grdAnalise.Columns[i].Name == "c8")
					{
						grdAnalise.Columns[i].HeaderText = "ERT";
					}
					else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10".Contains(grdAnalise.Columns[i].Name))
					{
						grdAnalise.Columns[i].Visible = false;
					}
				}
				else if (grdAnalise.Columns[i].Name == "c1")
				{
					grdAnalise.Columns[i].HeaderText = "Temperature";
				}
				else if (grdAnalise.Columns[i].Name == "c2")
				{
					grdAnalise.Columns[i].HeaderText = "Tol.Min";
				}
				else if (grdAnalise.Columns[i].Name == "c3")
				{
					grdAnalise.Columns[i].HeaderText = "Tol.Max";
				}
				else if ("c1,c2,c3,c4,c5,c6,c7,c8,c9,c10,tag".Contains(grdAnalise.Columns[i].Name))
				{
					grdAnalise.Columns[i].Visible = false;
				}
			}
		}
		catch (Exception ex)
		{
			MessageBox.Show(ex.Message);
		}
		btnGerar.Enabled = true;
		Cursor = Cursors.Default;
	}

	private void downloadDeDadosToolStripMenuItem_Click(object sender, EventArgs e)
	{
		new frmDownloadData().ShowDialog();
		btnGerar_Click(sender, e);
	}

	private void equipamentosToolStripMenuItem_Click(object sender, EventArgs e)
	{
		new frmEquipamentos().ShowDialog();
		CarregaEquipamentos();
		btnGerar_Click(sender, e);
	}

	private void grdAnalise_SelectionChanged(object sender, EventArgs e)
	{
		if (grdAnalise.CurrentRow != null && grdAnalise.CurrentRow.Cells[1].Value != null)
		{
			atualizaTabDetalhe();
		}
	}

	private void atualizaTabDetalhe()
	{
		SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("SELECT * FROM AnaliseItens WHERE id_Analise=@ID AND temperatura>0", sQLiteConnection);
		try
		{
			sQLiteConnection.Open();
			if (grdAnalise.DataSource != null)
			{
				sQLiteCommand.Parameters.AddWithValue("@ID", grdAnalise.CurrentRow.Cells[2].Value);
			}
			else
			{
				sQLiteCommand.Parameters.AddWithValue("@ID", null);
			}
			tblAnaliseData.Clear();
			tblAnaliseData.Load(sQLiteCommand.ExecuteReader());
			sQLiteConnection.Close();
			foreach (DataRow row in tblAnaliseData.Rows)
			{
				row.BeginEdit();
				row["temperatura"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["temperatura"]));
				row["derivada"] = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, Convert.ToDouble(row["derivada"]) * -1.0);
				row.EndEdit();
			}
			for (int i = 0; i < chtTempDeriv.Series.Count; i++)
			{
				chtTempDeriv.Series[i].Points.Clear();
			}
			grdData.DataSource = tblAnaliseData;
			chtTempDeriv.DataSource = tblAnaliseData;
			chtTempDeriv.DataBind();
			chtTempDeriv.Series[1].Enabled = cboModo.SelectedIndex != 4;
			grdData.Columns[0].HeaderText = "ID";
			grdData.Columns[1].Visible = false;
			grdData.Columns[2].DefaultCellStyle = style1;
			grdData.Columns[3].DefaultCellStyle = style2;
			grdData.Columns[4].DefaultCellStyle = style2;
			if (defLanguage == 1)
			{
				grdData.Columns[2].HeaderText = "Period";
				grdData.Columns[3].HeaderText = "Temperature";
				grdData.Columns[4].HeaderText = "Derived";
				chtTempDeriv.ChartAreas[0].Axes[0].Title = "Period";
				chtTempDeriv.Series[0].Name = "Temperature";
				if (cboModo.SelectedIndex == 4)
				{
					chtTempDeriv.Series[1].Name = "Target";
				}
			}
			else if (cboModo.SelectedIndex == 4)
			{
				chtTempDeriv.Series[1].Name = "Alvo";
			}
		}
		catch (Exception ex)
		{
			MessageBox.Show(ex.Message);
		}
	}

	private void mniDeleteAllData_Click(object sender, EventArgs e)
	{
		if ((defLanguage == 0 && MessageBox.Show("Este procedimento ira excluir todos os registros do banco de dados!\n\nConfirma a exclusão?", "Exclusão de dados!", MessageBoxButtons.YesNo, MessageBoxIcon.Exclamation) != DialogResult.Yes) || (defLanguage == 1 && MessageBox.Show("This procedure will delete all records from the database! \n\n Do you confirm the deletion?", "Deleting Data!", MessageBoxButtons.YesNo, MessageBoxIcon.Exclamation) != DialogResult.Yes))
		{
			return;
		}
		try
		{
			SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
			SQLiteCommand sQLiteCommand = new SQLiteCommand("DELETE FROM Analise", sQLiteConnection);
			SQLiteCommand sQLiteCommand2 = new SQLiteCommand("DELETE FROM AnaliseItens", sQLiteConnection);
			sQLiteConnection.Open();
			sQLiteCommand.ExecuteNonQuery();
			sQLiteCommand2.ExecuteNonQuery();
			sQLiteCommand.CommandText = "VACUUM";
			sQLiteCommand.ExecuteNonQuery();
			sQLiteConnection.Close();
			btnGerar_Click(sender, e);
			MessageBox.Show("All Data Deleted!");
		}
		catch (Exception ex)
		{
			MessageBox.Show(ex.Message, "DELETE ALL DATA");
		}
	}

	private void cboModo_SelectedIndexChanged(object sender, EventArgs e)
	{
		btnGerar_Click(sender, e);
	}

	private void sairToolStripMenuItem_Click(object sender, EventArgs e)
	{
		Application.Exit();
	}

	private void LanguageSet(int pLang)
	{
		if (pLang != defLanguage)
		{
			defLanguage = pLang;
			if (defLanguage == 1)
			{
				trocarIdioma("en-US");
			}
			else
			{
				trocarIdioma("pt-BR");
			}
			Configuration configuration = ConfigurationManager.OpenExeConfiguration(ConfigurationUserLevel.None);
			configuration.AppSettings.Settings["Language"].Value = defLanguage.ToString();
			configuration.Save(ConfigurationSaveMode.Minimal);
			btEng.Enabled = defLanguage == 0;
			btPor.Enabled = defLanguage == 1;
		}
	}

	private void btEng_Click(object sender, EventArgs e)
	{
		LanguageSet(1);
	}

	private void btPor_Click(object sender, EventArgs e)
	{
		LanguageSet(0);
	}

	private void btAbout_Click(object sender, EventArgs e)
	{
		new frmAbout().ShowDialog();
		btnGerar_Click(sender, e);
	}

	private void toolStripMenuItem1_Click(object sender, EventArgs e)
	{
		new frmDados().ShowDialog();
		btnGerar_Click(sender, e);
	}

	private void cboUN_SelectedIndexChanged(object sender, EventArgs e)
	{
		if (cboModo.SelectedIndex != -1)
		{
			defUnity = cboUN.SelectedIndex;
			un = ((cboUN.SelectedIndex == 1) ? "°F" : "°C");
			if (defLanguage == 1)
			{
				chtTempDeriv.ChartAreas[0].Axes[1].Title = "Temperature " + un;
				chtTempDeriv.ChartAreas[0].Axes[3].Title = "Derivative " + un + " / sec";
			}
			else
			{
				chtTempDeriv.ChartAreas[0].Axes[1].Title = "Temperatura " + un;
				chtTempDeriv.ChartAreas[0].Axes[3].Title = "Derivada " + un + " / seg";
			}
			chtTempDeriv.ChartAreas[0].Axes[3].Minimum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, -6.0);
			chtTempDeriv.ChartAreas[0].Axes[3].Maximum = Converters.ConvertCelsiusToFahrenheit(cboUN.SelectedIndex, 6.0);
			btnGerar_Click(sender, e);
			Configuration configuration = ConfigurationManager.OpenExeConfiguration(ConfigurationUserLevel.None);
			configuration.AppSettings.Settings["Unity"].Value = cboUN.SelectedIndex.ToString();
			configuration.Save(ConfigurationSaveMode.Minimal);
		}
	}

	private void grdAnalise_CellMouseMove(object sender, DataGridViewCellMouseEventArgs e)
	{
		if (e.ColumnIndex < 2)
		{
			grdAnalise.Cursor = Cursors.Hand;
		}
		else
		{
			grdAnalise.Cursor = Cursors.Arrow;
		}
	}

	private void grdAnalise_CellContentClick(object sender, DataGridViewCellEventArgs e)
	{
		if (e.RowIndex != -1)
		{
			if (grdAnalise.CurrentRow == null)
			{
				return;
			}
			Cursor = Cursors.WaitCursor;
			if (e.ColumnIndex == grdAnalise.Columns["colPDF"].Index)
			{
				try
				{
					frmReport001 frm = new frmReport001();
					frm.registro = Convert.ToInt32(grdAnalise.Rows[e.RowIndex].Cells["id"].Value);
					frm.Unidade = cboUN.Text;
					frm.dsData = new DataSet("dsData");
					DataTable table = tblAnalise.Clone();
					DataTable table2 = tblAnaliseData.Clone();
					DataTable dataTable = new DataTable("AnaliseName");
					dataTable.Columns.Add("cabecalho", typeof(string));
					dataTable.Columns.Add("ip", typeof(string));
					dataTable.Columns.Add("descricao", typeof(string));
					dataTable.Columns.Add("modo", typeof(string));
					dataTable.Columns.Add("canal", typeof(string));
					dataTable.Columns.Add("material", typeof(string));
					dataTable.Columns.Add("lote", typeof(string));
					dataTable.Columns.Add("unidade", typeof(string));
					dataTable.Columns.Add("dtinicio", typeof(string));
					dataTable.Columns.Add("dttermino", typeof(string));
					dataTable.Columns.Add("observacao", typeof(string));
					dataTable.Columns.Add("c1", typeof(string));
					dataTable.Columns.Add("c2", typeof(string));
					dataTable.Columns.Add("c3", typeof(string));
					dataTable.Columns.Add("c4", typeof(string));
					dataTable.Columns.Add("c5", typeof(string));
					dataTable.Columns.Add("c6", typeof(string));
					dataTable.Columns.Add("c7", typeof(string));
					dataTable.Columns.Add("c8", typeof(string));
					dataTable.Columns.Add("c9", typeof(string));
					dataTable.Columns.Add("c10", typeof(string));
					(from m in tblAnalise.AsEnumerable()
						where Convert.ToInt32(m["id"]) == frm.registro
						select m).CopyToDataTable(table, LoadOption.OverwriteChanges);
					tblAnaliseData.AsEnumerable().CopyToDataTable(table2, LoadOption.OverwriteChanges);
					frm.dsData.Tables.Add(table);
					frm.dsData.Tables.Add(table2);
					if (cboModo.SelectedIndex == 0)
					{
						if (defLanguage == 0)
						{
							dataTable.Rows.Add("RELATÓRIO DETALHADO CARBONO", "IP:", "Equipamento:", "Modo:", "Canal:", "Material:", "Lote:", "Unidade:", "Data Início:", "Data Término:", "Observação:", "Pico:", "TL:", "CE:", "TS:", "C:", "Si:", "TF:", "", "", "");
						}
						else
						{
							dataTable.Rows.Add("CARBON DETAILED REPORT", "IP:", "Device:", "Mode:", "Channel:", "Material:", "Lot:", "Unit:", "Start Date:", "Stop Date:", "Observation:", "Peak:", "TL:", "CE:", "TS:", "C:", "Si:", "EF:", "", "", "");
						}
						frm.dsData.Tables.Add(dataTable);
						frm.rptViewer.LocalReport.ReportPath = Application.StartupPath + "\\Reports\\rdlc\\ReportCarb.rdlc";
					}
					else if (cboModo.SelectedIndex == 1)
					{
						if (defLanguage == 0)
						{
							dataTable.Rows.Add("RELATÓRIO DETALHADO MICROESTRUTURA", "IP:", "Equipamento:", "Modo:", "Canal:", "Material:", "Lote:", "Unidade:", "Data Início:", "Data Término:", "Observação:", "Pico:", "TL:", "CE:", "TSE:", "TRE:", "REC:", "∆REC " + un + "/s:", "TF", "", "");
						}
						else
						{
							dataTable.Rows.Add("MICROSTRUCTURE DETAILED REPORT", "IP:", "Device:", "Mode:", "Channel:", "Material:", "Lot:", "Unit:", "Start Date:", "Stop Date:", "Observation:", "Peak:", "TL:", "CE:", "TEU:", "TER:", "REC:", "∆REC " + un + "/s:", "TF", "", "");
						}
						frm.dsData.Tables.Add(dataTable);
						frm.rptViewer.LocalReport.ReportPath = Application.StartupPath + "\\Reports\\rdlc\\ReportMicro.rdlc";
					}
					else if (cboModo.SelectedIndex == 2)
					{
						if (defLanguage == 0)
						{
							dataTable.Rows.Add("RELATÓRIO DETALHADO NiCro", "IP:", "Equipamento:", "Modo:", "Canal:", "Material:", "Lote:", "Unidade:", "Data Início:", "Data Término:", "Observação:", "Pico:", "TL:", "CE:", "Eutet:", "RecEut:", "REC:", "∆REC " + un + "/s:", "Solid", "", "");
						}
						else
						{
							dataTable.Rows.Add("NiCro DETAILED REPORT", "IP:", "Device:", "Mode:", "Channel:", "Material:", "Lot:", "Unit:", "Start Date:", "Stop Date:", "Observation:", "Peak:", "TL:", "CE:", "Eutet:", "RecEut:", "REC:", "∆REC " + un + "/s:", "Solid", "", "");
						}
						frm.dsData.Tables.Add(dataTable);
						frm.rptViewer.LocalReport.ReportPath = Application.StartupPath + "\\Reports\\rdlc\\ReportNiCro.rdlc";
					}
					else if (cboModo.SelectedIndex == 3)
					{
						if (defLanguage == 0)
						{
							dataTable.Rows.Add("RELATÓRIO DETALHADO ALUMINIO", "IP:", "Equipamento:", "Modo:", "Canal:", "Material:", "Lote:", "Unidade:", "Data Início:", "Data Término:", "Observação:", "Pico:", "TNL:", "RecL:", "TLiq:", "TEM:", "TER:", "RecE:", "TRE", "", "");
						}
						else
						{
							dataTable.Rows.Add("ALUMINUM DETAIL REPORT", "IP:", "Device:", "Mode:", "Channel:", "Material:", "Lot:", "Unit:", "Start Date:", "Stop Date:", "Observation:", "Peak:", "TNL:", "LRec", "LRT:", "TEU:", "TER:", "EutR:", "ERT", "", "");
						}
						frm.dsData.Tables.Add(dataTable);
						frm.rptViewer.LocalReport.ReportPath = Application.StartupPath + "\\Reports\\rdlc\\ReportAlum.rdlc";
					}
					else
					{
						if (defLanguage == 0)
						{
							dataTable.Rows.Add("RELATÓRIO DETALHADO LANÇA", "IP:", "Equipamento:", "Modo:", "Canal:", "Material:", "Lote:", "Unidade:", "Data Início:", "Data Término:", "Observação:", "ALVO:", "TOL.MIN:", "TOL.MAX:", "", "", "", "", "", "", "");
						}
						else
						{
							dataTable.Rows.Add("LANCE DETAIL REPORT", "IP:", "Device:", "Mode:", "Channel:", "Material:", "Lot:", "Unit:", "Start Date:", "Stop Date:", "Observation:", "TARGET:", "TOL.MIN:", "TOL.MAX:", "", "", "", "", "", "", "");
						}
						frm.dsData.Tables.Add(dataTable);
						frm.rptViewer.LocalReport.ReportPath = Application.StartupPath + "\\Reports\\rdlc\\ReportLanca.rdlc";
					}
					frm.ShowDialog();
					frm.Dispose();
				}
				catch (Exception ex)
				{
					MessageBox.Show(ex.Message);
				}
			}
			else if (e.ColumnIndex == grdAnalise.Columns["colXLS"].Index)
			{
				Cursor = Cursors.WaitCursor;
				Converters.SaveDataRowGridViewToXLS(grdAnalise, grdData);
				Cursor = Cursors.Default;
			}
		}
		Cursor = Cursors.Default;
	}

	private void btReport_Click(object sender, EventArgs e)
	{
		if (grdAnalise.CurrentRow != null)
		{
			Cursor = Cursors.WaitCursor;
			Converters.SaveDataGridViewToXLS(grdAnalise);
			Cursor = Cursors.Default;
		}
	}

	private void tab_SelectedIndexChanged(object sender, EventArgs e)
	{
		btReport.Enabled = tab.SelectedTab == tabAnalise;
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
		this.components = new System.ComponentModel.Container();
		System.ComponentModel.ComponentResourceManager resources = new System.ComponentModel.ComponentResourceManager(typeof(CarbomaxDelta.frmMain));
		System.Windows.Forms.DataVisualization.Charting.ChartArea chartArea = new System.Windows.Forms.DataVisualization.Charting.ChartArea();
		System.Windows.Forms.DataVisualization.Charting.Legend legend = new System.Windows.Forms.DataVisualization.Charting.Legend();
		System.Windows.Forms.DataVisualization.Charting.Series series = new System.Windows.Forms.DataVisualization.Charting.Series();
		System.Windows.Forms.DataVisualization.Charting.Series series2 = new System.Windows.Forms.DataVisualization.Charting.Series();
		this.tab = new System.Windows.Forms.TabControl();
		this.tabAnalise = new System.Windows.Forms.TabPage();
		this.grdAnalise = new System.Windows.Forms.DataGridView();
		this.colPDF = new System.Windows.Forms.DataGridViewImageColumn();
		this.colXLS = new System.Windows.Forms.DataGridViewImageColumn();
		this.tabDados = new System.Windows.Forms.TabPage();
		this.grdData = new System.Windows.Forms.DataGridView();
		this.tabGrafico = new System.Windows.Forms.TabPage();
		this.chtTempDeriv = new System.Windows.Forms.DataVisualization.Charting.Chart();
		this.menuStrip1 = new System.Windows.Forms.MenuStrip();
		this.arquivoToolStripMenuItem = new System.Windows.Forms.ToolStripMenuItem();
		this.equipamentosToolStripMenuItem = new System.Windows.Forms.ToolStripMenuItem();
		this.toolStripSeparator1 = new System.Windows.Forms.ToolStripSeparator();
		this.downloadDeDadosToolStripMenuItem = new System.Windows.Forms.ToolStripMenuItem();
		this.mniDeleteAllData = new System.Windows.Forms.ToolStripMenuItem();
		this.mniTabelaDados = new System.Windows.Forms.ToolStripMenuItem();
		this.toolStripSeparator2 = new System.Windows.Forms.ToolStripSeparator();
		this.sairToolStripMenuItem = new System.Windows.Forms.ToolStripMenuItem();
		this.txtDtInicio = new System.Windows.Forms.DateTimePicker();
		this.txtDtTermino = new System.Windows.Forms.DateTimePicker();
		this.cboEquipamentoIni = new System.Windows.Forms.ComboBox();
		this.lblPeriodo = new System.Windows.Forms.Label();
		this.lblEquip = new System.Windows.Forms.Label();
		this.lblUnid = new System.Windows.Forms.Label();
		this.cboUN = new System.Windows.Forms.ComboBox();
		this.saveFileDialog1 = new System.Windows.Forms.SaveFileDialog();
		this.cboModo = new System.Windows.Forms.ComboBox();
		this.lblModo = new System.Windows.Forms.Label();
		this.toolStrip1 = new System.Windows.Forms.ToolStrip();
		this.btTools = new System.Windows.Forms.ToolStripButton();
		this.toolStripSeparator5 = new System.Windows.Forms.ToolStripSeparator();
		this.btDown = new System.Windows.Forms.ToolStripButton();
		this.toolStripSeparator6 = new System.Windows.Forms.ToolStripSeparator();
		this.btReport = new System.Windows.Forms.ToolStripButton();
		this.toolStripSeparator3 = new System.Windows.Forms.ToolStripSeparator();
		this.toolStripSeparator7 = new System.Windows.Forms.ToolStripSeparator();
		this.btAbout = new System.Windows.Forms.ToolStripButton();
		this.toolStripSeparator4 = new System.Windows.Forms.ToolStripSeparator();
		this.btEng = new System.Windows.Forms.ToolStripButton();
		this.toolStripSeparator8 = new System.Windows.Forms.ToolStripSeparator();
		this.btPor = new System.Windows.Forms.ToolStripButton();
		this.btExit = new System.Windows.Forms.ToolStripButton();
		this.dataGridViewImageColumn1 = new System.Windows.Forms.DataGridViewImageColumn();
		this.dataGridViewImageColumn2 = new System.Windows.Forms.DataGridViewImageColumn();
		this.btnGerar = new System.Windows.Forms.Button();
		this.pictureBox7 = new System.Windows.Forms.PictureBox();
		this.pictureBox2 = new System.Windows.Forms.PictureBox();
		this.pictureBox1 = new System.Windows.Forms.PictureBox();
		this.analiseDataBindingSource = new System.Windows.Forms.BindingSource(this.components);
		this.tab.SuspendLayout();
		this.tabAnalise.SuspendLayout();
		((System.ComponentModel.ISupportInitialize)this.grdAnalise).BeginInit();
		this.tabDados.SuspendLayout();
		((System.ComponentModel.ISupportInitialize)this.grdData).BeginInit();
		this.tabGrafico.SuspendLayout();
		((System.ComponentModel.ISupportInitialize)this.chtTempDeriv).BeginInit();
		this.menuStrip1.SuspendLayout();
		this.toolStrip1.SuspendLayout();
		((System.ComponentModel.ISupportInitialize)this.pictureBox7).BeginInit();
		((System.ComponentModel.ISupportInitialize)this.pictureBox2).BeginInit();
		((System.ComponentModel.ISupportInitialize)this.pictureBox1).BeginInit();
		((System.ComponentModel.ISupportInitialize)this.analiseDataBindingSource).BeginInit();
		base.SuspendLayout();
		resources.ApplyResources(this.tab, "tab");
		this.tab.Controls.Add(this.tabAnalise);
		this.tab.Controls.Add(this.tabDados);
		this.tab.Controls.Add(this.tabGrafico);
		this.tab.Name = "tab";
		this.tab.SelectedIndex = 0;
		this.tab.SelectedIndexChanged += new System.EventHandler(tab_SelectedIndexChanged);
		this.tabAnalise.Controls.Add(this.grdAnalise);
		this.tabAnalise.ForeColor = System.Drawing.SystemColors.ControlText;
		resources.ApplyResources(this.tabAnalise, "tabAnalise");
		this.tabAnalise.Name = "tabAnalise";
		this.tabAnalise.UseVisualStyleBackColor = true;
		this.grdAnalise.AllowUserToAddRows = false;
		this.grdAnalise.AllowUserToDeleteRows = false;
		this.grdAnalise.AllowUserToResizeRows = false;
		this.grdAnalise.AutoSizeColumnsMode = System.Windows.Forms.DataGridViewAutoSizeColumnsMode.DisplayedCells;
		this.grdAnalise.BackgroundColor = System.Drawing.Color.White;
		this.grdAnalise.ColumnHeadersHeightSizeMode = System.Windows.Forms.DataGridViewColumnHeadersHeightSizeMode.AutoSize;
		this.grdAnalise.Columns.AddRange(this.colPDF, this.colXLS);
		resources.ApplyResources(this.grdAnalise, "grdAnalise");
		this.grdAnalise.MultiSelect = false;
		this.grdAnalise.Name = "grdAnalise";
		this.grdAnalise.ReadOnly = true;
		this.grdAnalise.SelectionMode = System.Windows.Forms.DataGridViewSelectionMode.FullRowSelect;
		this.grdAnalise.CellContentClick += new System.Windows.Forms.DataGridViewCellEventHandler(grdAnalise_CellContentClick);
		this.grdAnalise.CellMouseMove += new System.Windows.Forms.DataGridViewCellMouseEventHandler(grdAnalise_CellMouseMove);
		this.grdAnalise.SelectionChanged += new System.EventHandler(grdAnalise_SelectionChanged);
		this.colPDF.Frozen = true;
		resources.ApplyResources(this.colPDF, "colPDF");
		this.colPDF.Image = CarbomaxDelta.Properties.Resources.pdf;
		this.colPDF.Name = "colPDF";
		this.colPDF.ReadOnly = true;
		this.colPDF.Resizable = System.Windows.Forms.DataGridViewTriState.False;
		this.colXLS.Frozen = true;
		resources.ApplyResources(this.colXLS, "colXLS");
		this.colXLS.Image = CarbomaxDelta.Properties.Resources.xls;
		this.colXLS.Name = "colXLS";
		this.colXLS.ReadOnly = true;
		this.colXLS.Resizable = System.Windows.Forms.DataGridViewTriState.False;
		this.tabDados.Controls.Add(this.grdData);
		resources.ApplyResources(this.tabDados, "tabDados");
		this.tabDados.Name = "tabDados";
		this.tabDados.UseVisualStyleBackColor = true;
		this.grdData.AllowUserToAddRows = false;
		this.grdData.AllowUserToDeleteRows = false;
		this.grdData.AllowUserToResizeRows = false;
		this.grdData.AutoSizeColumnsMode = System.Windows.Forms.DataGridViewAutoSizeColumnsMode.DisplayedCells;
		this.grdData.BackgroundColor = System.Drawing.Color.White;
		this.grdData.ColumnHeadersHeightSizeMode = System.Windows.Forms.DataGridViewColumnHeadersHeightSizeMode.AutoSize;
		resources.ApplyResources(this.grdData, "grdData");
		this.grdData.MultiSelect = false;
		this.grdData.Name = "grdData";
		this.grdData.ReadOnly = true;
		this.grdData.SelectionMode = System.Windows.Forms.DataGridViewSelectionMode.FullRowSelect;
		this.tabGrafico.Controls.Add(this.chtTempDeriv);
		resources.ApplyResources(this.tabGrafico, "tabGrafico");
		this.tabGrafico.Name = "tabGrafico";
		this.tabGrafico.UseVisualStyleBackColor = true;
		this.chtTempDeriv.BackGradientStyle = System.Windows.Forms.DataVisualization.Charting.GradientStyle.TopBottom;
		this.chtTempDeriv.BackSecondaryColor = System.Drawing.Color.FromArgb(224, 224, 224);
		this.chtTempDeriv.BorderlineColor = System.Drawing.Color.Black;
		this.chtTempDeriv.BorderlineDashStyle = System.Windows.Forms.DataVisualization.Charting.ChartDashStyle.Solid;
		chartArea.AlignmentOrientation = System.Windows.Forms.DataVisualization.Charting.AreaAlignmentOrientations.All;
		chartArea.AxisX.IsStartedFromZero = false;
		chartArea.AxisX.LabelStyle.Format = "##0.0 s";
		chartArea.AxisX.MajorGrid.LineColor = System.Drawing.Color.DimGray;
		chartArea.AxisX.MajorGrid.LineDashStyle = System.Windows.Forms.DataVisualization.Charting.ChartDashStyle.Dot;
		chartArea.AxisX.MinorGrid.LineColor = System.Drawing.Color.Gainsboro;
		chartArea.AxisX.ScaleView.MinSizeType = System.Windows.Forms.DataVisualization.Charting.DateTimeIntervalType.Seconds;
		chartArea.AxisX2.IsStartedFromZero = false;
		chartArea.AxisX2.MajorGrid.Enabled = false;
		chartArea.AxisX2.MajorGrid.LineColor = System.Drawing.Color.Gainsboro;
		chartArea.AxisX2.MinorGrid.LineColor = System.Drawing.Color.Gainsboro;
		chartArea.AxisY.IsStartedFromZero = false;
		chartArea.AxisY.MajorGrid.Interval = 0.0;
		chartArea.AxisY.MajorGrid.LineColor = System.Drawing.Color.DimGray;
		chartArea.AxisY.MajorGrid.LineDashStyle = System.Windows.Forms.DataVisualization.Charting.ChartDashStyle.Dash;
		chartArea.AxisY.MinorGrid.LineColor = System.Drawing.Color.Gainsboro;
		chartArea.AxisY.Title = "Temperatura";
		chartArea.AxisY.TitleFont = new System.Drawing.Font("Microsoft Sans Serif", 12f, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, 0);
		chartArea.AxisY2.IsStartedFromZero = false;
		chartArea.AxisY2.MajorGrid.Enabled = false;
		chartArea.AxisY2.MajorGrid.LineColor = System.Drawing.Color.Gainsboro;
		chartArea.AxisY2.MinorGrid.LineColor = System.Drawing.Color.Gainsboro;
		chartArea.AxisY2.Title = "Derivada";
		chartArea.AxisY2.TitleFont = new System.Drawing.Font("Microsoft Sans Serif", 12f, System.Drawing.FontStyle.Regular, System.Drawing.GraphicsUnit.Point, 0);
		chartArea.BackColor = System.Drawing.Color.Black;
		chartArea.BorderColor = System.Drawing.Color.Silver;
		chartArea.Name = "ChartArea1";
		this.chtTempDeriv.ChartAreas.Add(chartArea);
		resources.ApplyResources(this.chtTempDeriv, "chtTempDeriv");
		legend.Enabled = false;
		legend.Name = "Legend1";
		this.chtTempDeriv.Legends.Add(legend);
		this.chtTempDeriv.Name = "chtTempDeriv";
		series.BorderWidth = 2;
		series.ChartArea = "ChartArea1";
		series.ChartType = System.Windows.Forms.DataVisualization.Charting.SeriesChartType.Line;
		series.Color = System.Drawing.Color.Red;
		series.IsVisibleInLegend = false;
		series.IsXValueIndexed = true;
		series.Legend = "Legend1";
		series.Name = "Temperatura";
		series.XValueMember = "Periodo";
		series.YValueMembers = "Temperatura";
		series2.ChartArea = "ChartArea1";
		series2.ChartType = System.Windows.Forms.DataVisualization.Charting.SeriesChartType.Line;
		series2.Color = System.Drawing.Color.Cyan;
		series2.IsVisibleInLegend = false;
		series2.IsXValueIndexed = true;
		series2.Legend = "Legend1";
		series2.Name = "Derivada";
		series2.XValueMember = "Periodo";
		series2.YAxisType = System.Windows.Forms.DataVisualization.Charting.AxisType.Secondary;
		series2.YValueMembers = "Derivada";
		this.chtTempDeriv.Series.Add(series);
		this.chtTempDeriv.Series.Add(series2);
		this.menuStrip1.Items.AddRange(new System.Windows.Forms.ToolStripItem[1] { this.arquivoToolStripMenuItem });
		resources.ApplyResources(this.menuStrip1, "menuStrip1");
		this.menuStrip1.Name = "menuStrip1";
		this.arquivoToolStripMenuItem.DropDownItems.AddRange(new System.Windows.Forms.ToolStripItem[7] { this.equipamentosToolStripMenuItem, this.toolStripSeparator1, this.downloadDeDadosToolStripMenuItem, this.mniDeleteAllData, this.mniTabelaDados, this.toolStripSeparator2, this.sairToolStripMenuItem });
		this.arquivoToolStripMenuItem.Name = "arquivoToolStripMenuItem";
		resources.ApplyResources(this.arquivoToolStripMenuItem, "arquivoToolStripMenuItem");
		this.equipamentosToolStripMenuItem.Name = "equipamentosToolStripMenuItem";
		resources.ApplyResources(this.equipamentosToolStripMenuItem, "equipamentosToolStripMenuItem");
		this.equipamentosToolStripMenuItem.Click += new System.EventHandler(equipamentosToolStripMenuItem_Click);
		this.toolStripSeparator1.Name = "toolStripSeparator1";
		resources.ApplyResources(this.toolStripSeparator1, "toolStripSeparator1");
		this.downloadDeDadosToolStripMenuItem.Name = "downloadDeDadosToolStripMenuItem";
		resources.ApplyResources(this.downloadDeDadosToolStripMenuItem, "downloadDeDadosToolStripMenuItem");
		this.downloadDeDadosToolStripMenuItem.Click += new System.EventHandler(downloadDeDadosToolStripMenuItem_Click);
		this.mniDeleteAllData.Name = "mniDeleteAllData";
		resources.ApplyResources(this.mniDeleteAllData, "mniDeleteAllData");
		this.mniDeleteAllData.Click += new System.EventHandler(mniDeleteAllData_Click);
		this.mniTabelaDados.Name = "mniTabelaDados";
		resources.ApplyResources(this.mniTabelaDados, "mniTabelaDados");
		this.mniTabelaDados.Click += new System.EventHandler(toolStripMenuItem1_Click);
		this.toolStripSeparator2.Name = "toolStripSeparator2";
		resources.ApplyResources(this.toolStripSeparator2, "toolStripSeparator2");
		this.sairToolStripMenuItem.Name = "sairToolStripMenuItem";
		resources.ApplyResources(this.sairToolStripMenuItem, "sairToolStripMenuItem");
		this.sairToolStripMenuItem.Click += new System.EventHandler(sairToolStripMenuItem_Click);
		resources.ApplyResources(this.txtDtInicio, "txtDtInicio");
		this.txtDtInicio.Format = System.Windows.Forms.DateTimePickerFormat.Custom;
		this.txtDtInicio.Name = "txtDtInicio";
		this.txtDtInicio.Value = new System.DateTime(2016, 1, 1, 0, 0, 0, 0);
		resources.ApplyResources(this.txtDtTermino, "txtDtTermino");
		this.txtDtTermino.Format = System.Windows.Forms.DateTimePickerFormat.Custom;
		this.txtDtTermino.Name = "txtDtTermino";
		this.cboEquipamentoIni.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList;
		this.cboEquipamentoIni.FormattingEnabled = true;
		resources.ApplyResources(this.cboEquipamentoIni, "cboEquipamentoIni");
		this.cboEquipamentoIni.Name = "cboEquipamentoIni";
		this.cboEquipamentoIni.SelectedIndexChanged += new System.EventHandler(cboEquipamentoIni_SelectedIndexChanged);
		resources.ApplyResources(this.lblPeriodo, "lblPeriodo");
		this.lblPeriodo.Name = "lblPeriodo";
		resources.ApplyResources(this.lblEquip, "lblEquip");
		this.lblEquip.Name = "lblEquip";
		resources.ApplyResources(this.lblUnid, "lblUnid");
		this.lblUnid.Name = "lblUnid";
		this.cboUN.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList;
		this.cboUN.FormattingEnabled = true;
		this.cboUN.Items.AddRange(new object[2]
		{
			resources.GetString("cboUN.Items"),
			resources.GetString("cboUN.Items1")
		});
		resources.ApplyResources(this.cboUN, "cboUN");
		this.cboUN.Name = "cboUN";
		this.cboUN.SelectedIndexChanged += new System.EventHandler(cboUN_SelectedIndexChanged);
		this.saveFileDialog1.FileName = "CarboxMaxDelta.csv";
		resources.ApplyResources(this.saveFileDialog1, "saveFileDialog1");
		this.cboModo.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList;
		this.cboModo.FormattingEnabled = true;
		this.cboModo.Items.AddRange(new object[5]
		{
			resources.GetString("cboModo.Items"),
			resources.GetString("cboModo.Items1"),
			resources.GetString("cboModo.Items2"),
			resources.GetString("cboModo.Items3"),
			resources.GetString("cboModo.Items4")
		});
		resources.ApplyResources(this.cboModo, "cboModo");
		this.cboModo.Name = "cboModo";
		this.cboModo.SelectedIndexChanged += new System.EventHandler(cboModo_SelectedIndexChanged);
		resources.ApplyResources(this.lblModo, "lblModo");
		this.lblModo.Name = "lblModo";
		this.toolStrip1.ImageScalingSize = new System.Drawing.Size(32, 32);
		this.toolStrip1.Items.AddRange(new System.Windows.Forms.ToolStripItem[13]
		{
			this.btTools, this.toolStripSeparator5, this.btDown, this.toolStripSeparator6, this.btReport, this.toolStripSeparator3, this.toolStripSeparator7, this.btAbout, this.toolStripSeparator4, this.btEng,
			this.toolStripSeparator8, this.btPor, this.btExit
		});
		resources.ApplyResources(this.toolStrip1, "toolStrip1");
		this.toolStrip1.Name = "toolStrip1";
		this.btTools.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btTools.Image = CarbomaxDelta.Properties.Resources._tools_icon;
		resources.ApplyResources(this.btTools, "btTools");
		this.btTools.Name = "btTools";
		this.btTools.Click += new System.EventHandler(equipamentosToolStripMenuItem_Click);
		this.toolStripSeparator5.Name = "toolStripSeparator5";
		resources.ApplyResources(this.toolStripSeparator5, "toolStripSeparator5");
		this.btDown.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btDown.Image = CarbomaxDelta.Properties.Resources.Download_Database_icon;
		resources.ApplyResources(this.btDown, "btDown");
		this.btDown.Name = "btDown";
		this.btDown.Click += new System.EventHandler(downloadDeDadosToolStripMenuItem_Click);
		this.toolStripSeparator6.Name = "toolStripSeparator6";
		resources.ApplyResources(this.toolStripSeparator6, "toolStripSeparator6");
		this.btReport.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btReport.Image = CarbomaxDelta.Properties.Resources.excel2;
		resources.ApplyResources(this.btReport, "btReport");
		this.btReport.Name = "btReport";
		this.btReport.Click += new System.EventHandler(btReport_Click);
		this.toolStripSeparator3.Name = "toolStripSeparator3";
		resources.ApplyResources(this.toolStripSeparator3, "toolStripSeparator3");
		this.toolStripSeparator7.Alignment = System.Windows.Forms.ToolStripItemAlignment.Right;
		this.toolStripSeparator7.Name = "toolStripSeparator7";
		resources.ApplyResources(this.toolStripSeparator7, "toolStripSeparator7");
		this.btAbout.Alignment = System.Windows.Forms.ToolStripItemAlignment.Right;
		this.btAbout.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btAbout.Image = CarbomaxDelta.Properties.Resources.Logo_2013;
		resources.ApplyResources(this.btAbout, "btAbout");
		this.btAbout.Name = "btAbout";
		this.btAbout.Click += new System.EventHandler(btAbout_Click);
		this.toolStripSeparator4.Alignment = System.Windows.Forms.ToolStripItemAlignment.Right;
		this.toolStripSeparator4.Name = "toolStripSeparator4";
		resources.ApplyResources(this.toolStripSeparator4, "toolStripSeparator4");
		this.btEng.Alignment = System.Windows.Forms.ToolStripItemAlignment.Right;
		this.btEng.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btEng.Image = CarbomaxDelta.Properties.Resources.United_States_Flag_icon;
		resources.ApplyResources(this.btEng, "btEng");
		this.btEng.Name = "btEng";
		this.btEng.Click += new System.EventHandler(btEng_Click);
		this.toolStripSeparator8.Alignment = System.Windows.Forms.ToolStripItemAlignment.Right;
		this.toolStripSeparator8.Name = "toolStripSeparator8";
		resources.ApplyResources(this.toolStripSeparator8, "toolStripSeparator8");
		this.btPor.Alignment = System.Windows.Forms.ToolStripItemAlignment.Right;
		this.btPor.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btPor.Image = CarbomaxDelta.Properties.Resources.Brazil_Flag_icon;
		resources.ApplyResources(this.btPor, "btPor");
		this.btPor.Name = "btPor";
		this.btPor.Click += new System.EventHandler(btPor_Click);
		this.btExit.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btExit.Image = CarbomaxDelta.Properties.Resources.exit;
		resources.ApplyResources(this.btExit, "btExit");
		this.btExit.Name = "btExit";
		this.btExit.Click += new System.EventHandler(sairToolStripMenuItem_Click);
		this.dataGridViewImageColumn1.FillWeight = 25f;
		this.dataGridViewImageColumn1.Frozen = true;
		resources.ApplyResources(this.dataGridViewImageColumn1, "dataGridViewImageColumn1");
		this.dataGridViewImageColumn1.Image = CarbomaxDelta.Properties.Resources.pdf;
		this.dataGridViewImageColumn1.Name = "dataGridViewImageColumn1";
		this.dataGridViewImageColumn1.ReadOnly = true;
		this.dataGridViewImageColumn1.Resizable = System.Windows.Forms.DataGridViewTriState.False;
		resources.ApplyResources(this.dataGridViewImageColumn2, "dataGridViewImageColumn2");
		this.dataGridViewImageColumn2.Image = CarbomaxDelta.Properties.Resources.xls;
		this.dataGridViewImageColumn2.Name = "dataGridViewImageColumn2";
		this.dataGridViewImageColumn2.ReadOnly = true;
		this.dataGridViewImageColumn2.Resizable = System.Windows.Forms.DataGridViewTriState.False;
		this.btnGerar.BackColor = System.Drawing.Color.Transparent;
		this.btnGerar.FlatAppearance.BorderSize = 0;
		resources.ApplyResources(this.btnGerar, "btnGerar");
		this.btnGerar.ForeColor = System.Drawing.Color.White;
		this.btnGerar.Image = CarbomaxDelta.Properties.Resources.refresh;
		this.btnGerar.Name = "btnGerar";
		this.btnGerar.UseVisualStyleBackColor = false;
		this.btnGerar.Click += new System.EventHandler(btnGerar_Click);
		resources.ApplyResources(this.pictureBox7, "pictureBox7");
		this.pictureBox7.Image = CarbomaxDelta.Properties.Resources.logo2;
		this.pictureBox7.Name = "pictureBox7";
		this.pictureBox7.TabStop = false;
		this.pictureBox2.Image = CarbomaxDelta.Properties.Resources.im_fir;
		resources.ApplyResources(this.pictureBox2, "pictureBox2");
		this.pictureBox2.Name = "pictureBox2";
		this.pictureBox2.TabStop = false;
		this.pictureBox1.Image = CarbomaxDelta.Properties.Resources.im_las;
		resources.ApplyResources(this.pictureBox1, "pictureBox1");
		this.pictureBox1.Name = "pictureBox1";
		this.pictureBox1.TabStop = false;
		resources.ApplyResources(this, "$this");
		base.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
		base.Controls.Add(this.toolStrip1);
		base.Controls.Add(this.cboModo);
		base.Controls.Add(this.lblModo);
		base.Controls.Add(this.btnGerar);
		base.Controls.Add(this.pictureBox7);
		base.Controls.Add(this.cboUN);
		base.Controls.Add(this.lblUnid);
		base.Controls.Add(this.pictureBox2);
		base.Controls.Add(this.pictureBox1);
		base.Controls.Add(this.lblEquip);
		base.Controls.Add(this.lblPeriodo);
		base.Controls.Add(this.cboEquipamentoIni);
		base.Controls.Add(this.txtDtTermino);
		base.Controls.Add(this.txtDtInicio);
		base.Controls.Add(this.tab);
		base.Controls.Add(this.menuStrip1);
		base.MainMenuStrip = this.menuStrip1;
		base.Name = "frmMain";
		base.Load += new System.EventHandler(frmMain_Load);
		this.tab.ResumeLayout(false);
		this.tabAnalise.ResumeLayout(false);
		((System.ComponentModel.ISupportInitialize)this.grdAnalise).EndInit();
		this.tabDados.ResumeLayout(false);
		((System.ComponentModel.ISupportInitialize)this.grdData).EndInit();
		this.tabGrafico.ResumeLayout(false);
		((System.ComponentModel.ISupportInitialize)this.chtTempDeriv).EndInit();
		this.menuStrip1.ResumeLayout(false);
		this.menuStrip1.PerformLayout();
		this.toolStrip1.ResumeLayout(false);
		this.toolStrip1.PerformLayout();
		((System.ComponentModel.ISupportInitialize)this.pictureBox7).EndInit();
		((System.ComponentModel.ISupportInitialize)this.pictureBox2).EndInit();
		((System.ComponentModel.ISupportInitialize)this.pictureBox1).EndInit();
		((System.ComponentModel.ISupportInitialize)this.analiseDataBindingSource).EndInit();
		base.ResumeLayout(false);
		base.PerformLayout();
	}
}
