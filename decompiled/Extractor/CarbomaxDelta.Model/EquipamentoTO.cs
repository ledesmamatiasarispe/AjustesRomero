namespace CarbomaxDelta.Model;

internal class EquipamentoTO
{
	public int EquipamentoID { get; set; }

	public string Descricao { get; set; }

	public string IP { get; set; }

	public EquipamentoTO(int ID, string Descricao, string IP)
	{
		EquipamentoID = ID;
		this.Descricao = Descricao;
		this.IP = IP;
	}

	public EquipamentoTO()
	{
	}
}
