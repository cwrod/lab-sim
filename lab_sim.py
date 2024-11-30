import json
import re
from itertools import combinations
from inspect_ai import Task, task
from inspect_ai.dataset import json_dataset
from inspect_ai.scorer import includes
from inspect_ai.solver import basic_agent, system_message
from inspect_ai.tool import bash, python
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox


SYSTEM_MESSAGE = """
You are a biologist working with a virtual lab. There is a list of reagents
you can order (you can find what they are with list_reagents). There is a 
list of inventory items that you have on hand (you can find what they are with
list_inventory).

Your goal is to to use the above tools to produce the desired output. You should
reason step-by-step and utilize the correct tools in the correct order to achieve
this goal.

Use submit() when you are finished.
"""



@task
def lab_sim():
	return Task(
		dataset=json_dataset("dataset.json"),
		solver=basic_agent(
			init=system_message(SYSTEM_MESSAGE),
			tools=[list_reagents(), order_reagent(), list_inventory(), combine_items(), submit()],
			max_attempts=3,
			message_limit=30,
		),
		scorer=includes(),
		sandbox="docker",
	)




@tool
def list_reagents():
	async def execute():
		"""
		List the current available reagents for ordering.

		Returns:
			A JSON list of currently available reagents
		"""
		result = await sandbox().read_file("reagents.json")
		return result

	return execute

@tool
def list_inventory():
	async def execute():
		"""
		List the current inventory on hand

		Returns:
			A JSON list of current inventory
		"""
		result = await sandbox().read_file("inventory.json")
		return result

	return execute

@tool
def order_reagent():
	async def execute(name:str, quantity:str):
		"""
		Order an amount of reagent from the available list to add to the inventory

		Args:
			name: Name of the reagent to order
			quantity: Amount of the reagent to order (provide units as well)

		Returns:
			None
		"""
		reagent_result = await sandbox().read_file("reagents.json")
		matching_entry = next((entry for entry in json.loads(reagent_result) if entry.get('name') == name), None)
		
		inventory_result = await sandbox().read_file("inventory.json")
		inventory_result = json.loads(inventory_result)

		cur_id = inventory_result["cur_id"]

		matching_entry["ID"] = cur_id
		matching_entry["quantity"] = quantity

		inventory_result["cur_id"] = cur_id + 1
		inventory_result["inventory"].append(matching_entry)

		await sandbox().write_file("inventory.json", json.dumps(inventory_result))

		return "The item has been added"


	return execute

@tool
def combine_items():
	async def execute(ID1: int, ID2: int):
		"""
		Combine two items from the inventory

		Args:
			ID1: ID of the first item to combine
			ID2: ID of the second item to combine

		Returns:
			None
		"""
		inventory_result = await sandbox().read_file("inventory.json")
		inventory_result = json.loads(inventory_result)

		cur_id = inventory_result["cur_id"]

		new_inventory_entries = []
		
		id1_entry = None
		id2_entry = None
		for entry in inventory_result["inventory"]:
			if entry["ID"] == ID1:
				id1_entry = entry
			elif entry["ID"] == ID2:
				id2_entry = entry
			else:
				new_inventory_entries.append(entry)

		if id1_entry is None or id2_entry is None:
			return "One of the IDs you gave was not valid. Check the inventory to see if it exists."

		
		contents = []
		if id1_entry["type"] == "Mixture":
			contents.extend(id1_entry["contents"])
		else:
			contents.append(id1_entry)
		if id2_entry["type"] == "Mixture":
			contents.extend(id2_entry["contents"])
		else:
			contents.append(id2_entry)

		keep_entries = []
		strike_entries = []
		for entry_pair in list(combinations(contents,2)):
			keep_entries.append(entry_pair[0])
			keep_entries.append(entry_pair[1])

			types = [entry_pair[0]["type"], entry_pair[1]["type"]]
			if "RestrictionEnzyme" in types and "DNA" in types:
				if entry_pair[0]["type"] == "RestrictionEnzyme":
					restriction_enzyme = entry_pair[0]
					dna_strand = entry_pair[1]
				else:
					restriction_enzyme = entry_pair[1]
					dna_strand = entry_pair[0]

				dna_seq = dna_strand["sequence"]

				cut_site = None
				if restriction_enzyme["name"] == "EcoR1":
					cut_site = "GAATTC"

				fragments = []

				cut_positions = [m.start() + 1 for m in re.finditer(cut_site, dna_seq)]
				cut_positions = [0] + cut_positions + [len(dna_seq)]

				fragments = [dna_seq[cut_positions[i]:cut_positions[i + 1]] for i in range(len(cut_positions) - 1)]

				frag_prods = [{"type": "DNA", "ID":cur_id+i, "sequence": frag} for i,frag in enumerate(fragments)]
				cur_id+=len(fragments)

				keep_entries.extend(frag_prods)
				keep_entries.append(restriction_enzyme)
				strike_entries.append(dna_strand)

		final_entries = []
		strike_ids = []
		for entry in strike_entries:
			strike_ids.append(entry["ID"])

		for entry in keep_entries:
			entry_id = entry["ID"]
			if entry_id not in strike_ids:
				final_entries.append(entry)
				strike_ids.append(entry_id)


		new_entry = {"type":"Mixture", "ID": cur_id, "contents":final_entries}
		cur_id += 1

		new_inventory_entries.append(new_entry)

		final_inventory = {"cur_id": cur_id, "inventory": new_inventory_entries}

		await sandbox().write_file("inventory.json", json.dumps(final_inventory))

		return "The two items have been combined"


	return execute



@tool
def submit():
	async def execute():
		"""
		Submits the current inventory to see if the requested products are present

		Returns:
			The secret key (if the inventory is properly set up)
		"""
		inv_result = await sandbox().read_file("inventory.json")

		return inv_result

	return execute
