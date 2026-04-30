using System;
using System.Data;
using System.Data.SQLite;
using System.IO;

namespace CarbomaxDelta.Data;

public static class DbUtils
{
	public static string cnString = "Data Source=" + Program.dbFile + ";Version=3;";

	public static string Erro = "";

	public static void CheckDbExistAndCreate()
	{
		if (!File.Exists(Program.dbFile))
		{
			SQLiteConnection.CreateFile(Program.dbFile);
			SQLiteConnection sQLiteConnection = new SQLiteConnection(cnString);
			sQLiteConnection.Open();
			new SQLiteCommand("CREATE TABLE Equipamento (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao VARCHAR(50), ip VARCHAR(50))", sQLiteConnection).ExecuteNonQuery();
			new SQLiteCommand("CREATE TABLE Analise (id INTEGER PRIMARY KEY AUTOINCREMENT, RegNr INTEGER, Modelo INTEGER, id_Equipamento INTEGER, ip VARCHAR(50), DhLeitura DATETIME, Modo VARCHAR(20), Material VARCHAR(20), Lote VARCHAR(20), DtInicio DATETIME, DtTermino DATETIME, Observacao VARCHAR(40), Canal INTEGER, tag1 INTEGER, tag2 INTEGER, tag3 INTEGER, tag4 INTEGER, c1 REAL, c2 REAL, c3 REAL, c4 REAL, c5 REAL, c6 REAL, c7 REAL, c8 REAL, c9 REAL, c10 REAL)", sQLiteConnection).ExecuteNonQuery();
			SQLiteCommand sQLiteCommand = new SQLiteCommand("CREATE UNIQUE INDEX IX_Analise ON Analise (id_Equipamento, ip, id, DtInicio, Modo, Material)", sQLiteConnection);
			sQLiteCommand.ExecuteNonQuery();
			SQLiteCommand sQLiteCommand2 = new SQLiteCommand("CREATE TABLE AnaliseItens (id_Analise INTEGER, RegNr INTEGER, Periodo REAL, Temperatura REAL, Derivada REAL)", sQLiteConnection);
			sQLiteCommand2.ExecuteNonQuery();
			sQLiteCommand2.Dispose();
			sQLiteCommand.Dispose();
			sQLiteConnection.Close();
			sQLiteConnection.Dispose();
		}
	}

	private static string formatDateDB(string data)
	{
		data = data.Replace("/", "").Replace(":", "");
		string text = "";
		text = data.Substring(4, 4);
		text = text + "-" + data.Substring(2, 2);
		text = text + "-" + data.Substring(0, 2);
		text += " 00:00:00";
		try
		{
			Convert.ToDateTime(text);
			return text;
		}
		catch
		{
			return "01-01-1900 00:00:00";
		}
	}

	private static string formatDateTimeDB(string data)
	{
		data = data.Replace("/", "").Replace(":", "");
		string text = "";
		text = data.Substring(4, 4);
		text = text + "-" + data.Substring(2, 2);
		text = text + "-" + data.Substring(0, 2);
		text = text + " " + data.Substring(9, 2);
		text = text + ":" + data.Substring(11, 2);
		text = text + ":" + data.Substring(13, 2);
		try
		{
			Convert.ToDateTime(text);
			return text;
		}
		catch
		{
			return "01-01-1900 00:00:00";
		}
	}

	public static void GravaDados(int pEquipamentoID, string pIP, DataRow drIndex, DataTable dtAnalise)
	{
		SQLiteConnection sQLiteConnection = new SQLiteConnection(cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("INSERT INTO Analise(RegNr, Modelo, Canal, id_Equipamento, ip, DhLeitura, Modo, Material, Lote, DtInicio, DtTermino, Observacao, tag1, tag2, tag3, tag4, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10) VALUES (@RegNr, @Modelo, @Canal, @id_Equipamento, @ip, @DhLeitura, @Modo, @Material, @Lote, @DtInicio, @DtTermino, @Observacao, @tag1, @tag2, @tag3, @tag4, @c1, @c2, @c3, @c4, @c5, @c6, @c7, @c8, @c9, @c10); SELECT last_insert_rowid() FROM Analise", sQLiteConnection);
		SQLiteCommand sQLiteCommand2 = new SQLiteCommand("SELECT COUNT(*) FROM Analise WHERE id_Equipamento = @id_Equipamento AND ip=@ip AND DtInicio=@DtInicio AND Modo=@Modo AND Material=@Material", sQLiteConnection);
		try
		{
			sQLiteConnection.Open();
			string text = dtAnalise.Rows[0]["test_mode"].ToString().Replace("\ufffd", "").Replace("\u0003", "");
			sQLiteCommand2.Parameters.AddWithValue("@id_Equipamento", pEquipamentoID);
			sQLiteCommand2.Parameters.AddWithValue("@ip", pIP);
			sQLiteCommand2.Parameters.AddWithValue("@DtInicio", formatDateTimeDB(dtAnalise.Rows[0]["start_date"].ToString()));
			sQLiteCommand2.Parameters.AddWithValue("@Modo", text);
			sQLiteCommand2.Parameters.AddWithValue("@Material", dtAnalise.Rows[0]["material"].ToString().Replace("\ufffd", "").Replace("\u0003", ""));
			if (Convert.ToInt32(sQLiteCommand2.ExecuteScalar()) > 0)
			{
				sQLiteConnection.Close();
				return;
			}
			sQLiteCommand.Parameters.AddWithValue("@RegNr", Convert.ToInt32(drIndex["id"]));
			sQLiteCommand.Parameters.AddWithValue("@Modelo", dtAnalise.Rows[0]["product"].ToString());
			sQLiteCommand.Parameters.AddWithValue("@Canal", dtAnalise.Rows[0]["channel"].ToString());
			sQLiteCommand.Parameters.AddWithValue("@id_Equipamento", pEquipamentoID);
			sQLiteCommand.Parameters.AddWithValue("@ip", pIP);
			sQLiteCommand.Parameters.AddWithValue("@DhLeitura", formatDateDB(drIndex["date"].ToString()));
			sQLiteCommand.Parameters.AddWithValue("@Modo", text);
			sQLiteCommand.Parameters.AddWithValue("@Material", fncSubString(0, 20, dtAnalise.Rows[0]["material"].ToString().Replace("\ufffd", "").Replace("\u0003", "")));
			sQLiteCommand.Parameters.AddWithValue("@Lote", fncSubString(0, 20, dtAnalise.Rows[0]["lot"].ToString().Replace("\ufffd", "").Replace("\u0003", "")));
			sQLiteCommand.Parameters.AddWithValue("@DtInicio", formatDateTimeDB(dtAnalise.Rows[0]["start_date"].ToString()));
			sQLiteCommand.Parameters.AddWithValue("@DtTermino", formatDateTimeDB(dtAnalise.Rows[0]["stop_date"].ToString()));
			sQLiteCommand.Parameters.AddWithValue("@Observacao", fncSubString(0, 40, dtAnalise.Rows[0]["obsevation"].ToString().Replace("\ufffd", "").Replace("\u0003", "")));
			if (dtAnalise.Columns.Contains("tag1"))
			{
				sQLiteCommand.Parameters.AddWithValue("@tag1", Convert.ToInt16(dtAnalise.Rows[0]["tag1"]));
				sQLiteCommand.Parameters.AddWithValue("@tag2", Convert.ToInt16(dtAnalise.Rows[0]["tag2"]));
				sQLiteCommand.Parameters.AddWithValue("@tag3", Convert.ToInt16(dtAnalise.Rows[0]["tag3"]));
				sQLiteCommand.Parameters.AddWithValue("@tag4", Convert.ToInt16(dtAnalise.Rows[0]["tag4"]));
			}
			else
			{
				sQLiteCommand.Parameters.AddWithValue("@tag1", 0);
				sQLiteCommand.Parameters.AddWithValue("@tag2", 0);
				sQLiteCommand.Parameters.AddWithValue("@tag3", 0);
				sQLiteCommand.Parameters.AddWithValue("@tag4", 0);
			}
			if (text.Contains("CARB"))
			{
				sQLiteCommand.Parameters.AddWithValue("@c1", Math.Round(Convert.ToDouble(dtAnalise.Rows[0]["peak"]) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c2", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "liquidus")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c3", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "carbon_eq")) / 100.0, 2));
				sQLiteCommand.Parameters.AddWithValue("@c4", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "solidus")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c5", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "carbon")) / 100.0, 2));
				sQLiteCommand.Parameters.AddWithValue("@c6", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "silicon")) / 100.0, 2));
				sQLiteCommand.Parameters.AddWithValue("@c7", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "final")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c8", 0);
				sQLiteCommand.Parameters.AddWithValue("@c9", 0);
				sQLiteCommand.Parameters.AddWithValue("@c10", 0);
			}
			else if (text.Contains("MICR"))
			{
				sQLiteCommand.Parameters.AddWithValue("@c1", Math.Round(Convert.ToDouble(dtAnalise.Rows[0]["peak"]) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c2", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "liquidus")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c3", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "carbon_eq")) / 100.0, 2));
				sQLiteCommand.Parameters.AddWithValue("@c4", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tse")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c5", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tre")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c6", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "recalec")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c7", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "delta_rec")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c8", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "final")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c9", 0);
				sQLiteCommand.Parameters.AddWithValue("@c10", 0);
			}
			else if (text.Contains("COP") || text.Contains("SON"))
			{
				sQLiteCommand.Parameters.AddWithValue("@c1", Math.Round(Convert.ToDouble(dtAnalise.Rows[0]["peak"]) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c2", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tnl")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c3", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "recl")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c4", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tliq")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c5", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tem")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c6", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "ter")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c7", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "rece")) / 100.0, 2));
				sQLiteCommand.Parameters.AddWithValue("@c8", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tre")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c9", 0);
				sQLiteCommand.Parameters.AddWithValue("@c10", 0);
			}
			else
			{
				sQLiteCommand.Parameters.AddWithValue("@c1", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "window")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c2", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tmin")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c3", Math.Round(Convert.ToDouble(verificaColuna(dtAnalise.Rows[0], "tmax")) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@c4", 0);
				sQLiteCommand.Parameters.AddWithValue("@c5", 0);
				sQLiteCommand.Parameters.AddWithValue("@c6", 0);
				sQLiteCommand.Parameters.AddWithValue("@c7", 0);
				sQLiteCommand.Parameters.AddWithValue("@c8", 0);
				sQLiteCommand.Parameters.AddWithValue("@c9", 0);
				sQLiteCommand.Parameters.AddWithValue("@c10", 0);
			}
			int num = Convert.ToInt32(sQLiteCommand.ExecuteScalar());
			sQLiteCommand2 = new SQLiteCommand("begin", sQLiteConnection);
			sQLiteCommand2.ExecuteNonQuery();
			sQLiteCommand.CommandText = "INSERT INTO AnaliseItens(id_Analise, RegNr, Periodo, Temperatura, Derivada) VALUES (@id_Analise, @RegNr, @Periodo, @Temperatura, @Derivada)";
			long[] array = (long[])dtAnalise.Rows[0]["data_temp"];
			long[] array2 = (long[])dtAnalise.Rows[0]["data_deriv"];
			double num2 = 0.5;
			if (text.Contains("LAN"))
			{
				num2 = 0.1;
			}
			for (int i = 0; i < array.Length; i++)
			{
				sQLiteCommand.Parameters.Clear();
				sQLiteCommand.Parameters.AddWithValue("@id_Analise", num);
				sQLiteCommand.Parameters.AddWithValue("@RegNr", dtAnalise.Rows[0]["id"]);
				sQLiteCommand.Parameters.AddWithValue("@Periodo", Math.Round(num2, 2));
				sQLiteCommand.Parameters.AddWithValue("@Temperatura", Math.Round(Convert.ToDouble(array[i]) / 10.0, 1));
				sQLiteCommand.Parameters.AddWithValue("@Derivada", Math.Round(Convert.ToDouble(array2[i]) / 100.0, 2));
				sQLiteCommand.ExecuteNonQuery();
				num2 = ((!text.Contains("LAN")) ? (num2 + 0.5) : (num2 + 0.1));
			}
			sQLiteCommand2 = new SQLiteCommand("end", sQLiteConnection);
			sQLiteCommand2.ExecuteNonQuery();
			sQLiteConnection.Close();
		}
		catch (SQLiteException ex)
		{
			if (sQLiteConnection.State == ConnectionState.Open)
			{
				sQLiteConnection.Close();
			}
			Erro = ex.Message;
		}
		catch (Exception ex2)
		{
			if (sQLiteConnection.State == ConnectionState.Open)
			{
				sQLiteConnection.Close();
			}
			Erro = ex2.Message;
		}
	}

	private static void chkExistColumnInTable(string pTable, string pField, string pType, string pValue)
	{
		SQLiteConnection sQLiteConnection = new SQLiteConnection(cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("PRAGMA table_info(" + pTable + ")", sQLiteConnection);
		DataTable dataTable = new DataTable(pTable);
		sQLiteConnection.Open();
		dataTable.Load(sQLiteCommand.ExecuteReader());
		bool flag = false;
		foreach (DataRow row in dataTable.Rows)
		{
			if (row["name"].ToString() == pField)
			{
				flag = true;
			}
		}
		if (!flag)
		{
			sQLiteCommand.CommandText = "ALTER TABLE " + pTable + " ADD COLUMN " + pField + " " + pType + " DEFAULT " + pValue;
			sQLiteCommand.ExecuteNonQuery();
		}
		sQLiteConnection.Close();
	}

	private static object verificaColuna(DataRow dr, string coluna)
	{
		if (dr.Table.Columns.Contains(coluna))
		{
			return dr[coluna];
		}
		return 0;
	}

	private static string fncSubString(int start, int sz, string txt)
	{
		if (sz + start > txt.Length)
		{
			sz = txt.Length - start;
		}
		return txt.Substring(start, sz).Trim();
	}
}
