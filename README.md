## Tools to Tag VMs and NSX Segments & Create NSX Groups using input from a CSV file

NSX Firewall security rules have the basic format of:

 
> **\<Source\>  \<Destination\> \<Services\> \<Action\> \<apply-to\>**
    
The Source, Destination, and apply-to are "grouping" definitions that can include IP addresses, Virtual Machines, NSX Networks, and so on.  The compute and network inventories that are members of these groups are dynamically changing all the time in a datacenter.  As such, the Source and Destination definitions should leverage dynamic grouping capabilities of NSX to ensure that their memberships are updated in real-time to inorder to gaurantee proper security posture.  The apply-to group is a policy or rule scope that will limit the application of the rule to only the VMs that are effective members of the group.  TheseGroups can be defined using, but not limited to:
  - Virtual Machine Tags: The group will be dynamically updated to include any newly added VM with the tags; similary, the removal of any VM with the same tags will be deleted from the group.
  - NSX Segment Tags: The group will be dynamically updated to include all the VMs that are connected to NSX Segments with these tags
  - Virtual Machine: These are static members; the deletion of a VM will exclude it from the effective membership of the group.  However, any additions must require a change to the group configuration.
  - NSX Segment: The Segments are static members of the group; the effective membership of the group will be all the VMs that are connected to these segments.  Any change to the segment membership requires a change to the group configuration
  - VM Name string patterns: The effective membership of the group will be dynamically updated to include any VMs with names matching the pattern criteria.

It's recommended to configure Groups with dynamic configuration to ensure that group memberships are updated automatically.  While name string pattern matches are dynamic, the NSX Manager must perform string matches against all VMs in the inventory.  This method is much more CPU and time consuming then memberships based on tags.

In a large datacenter with many applications, each of which comprises of any number of VMs, it could be challenging to for the security administrator to effectively identify all the VMs that are part of a Business Unit, Tenant, application, or any other boundary scopes.  NSX Intelligence can analyze traffic flows and create group and security policy recommendations.  However, if you are starting with a brown field environment of many pre-existing VMs, the amount of recommendations from NSXI could be overwhemingly large for you to effectively review and approve.

As such, it's recommended that you pre-seed NSX with some idea of the security boundaries.  For example, you may already know that all the VMs under a Tier1 or Tier0 Gateway belong to a specific Tenant or Business Unit.  Similarly, the networks used by your Test environment are different than your Production environment.  Or a specific application owner may have deployed all their VMs with a name that starts with the same prefix.  Or all the VMs that belong to a Site or Availability zone has names with the Site or AZ names embedded as substrings.

To get started, one Tenant may have provided such information, but other Tenants may not in a timely manner.  This is fine.  We can pre-seed NSX with the information that's available.  Once seeded, then we can configure NSXI to report and make recommendations based on only those groups.  The security admin can then review the recommendations and test the policies with the relevant owners, and then re-update the seeing information if required to reflect any feedbacks so that NSXI can leverage it to make even better recommendations.  

While we recommend NSXI as the analytic and recommendation engine due to it's comprehensive coverage and ease-of-use, it's not required.  Tools like VRNI can also analyze traffic flows based on the pre-seeded groups.  Or we could enable the default NSX firewall rule to log any hits; the hits then can be used to match against the effective IP memberships of the groups for analysis and rule building.

There are two primary scripts provided:
  - grouptag.py - this will read input from a comma seperated (CSV) file that contains pre-seed information.  This could be imported from a CMDB or manually entered through a spreadsheet.  It will generate JSON output with information for:
      - Tagging VMs
      - Tagging Segments
      - Creating Groups based on the Tags
  - grouptagapply.py - this will apply the JSON output from grouptag.py to NSX.  The script also has the ability to remove any changes applied to NSX from the grouptag.py JSON; you must have a copy of the JSON output for this use case.

## A word about NSX Tags
The NSX Tag has two attributes:
  - scope
  - tag value

While the scope is optional, the tag value is mandatory.  An example of a scope could be **Tenant**, where the tag values **Tenant1**, **Tenant2**, etc can be used to indicate the different tenants.  In this case, the scope is used to indicate that the VM is owned by a tenant, and the value identifies the specific tenant.  

## How to use the CSV template:
Import the sample template.csv into your favorite spreadsheet.  Update the spreadsheet with your seeding information, and then feed the CSV export into grouptag.py.  Some general comments about the CSV and format:
  - There must be a header row; this doesn't have to be the first row.  The header row is identified where one of the columns has the word: **ObjectType**
  - The Header row must additionally have a column with **_SEP_** as the name; this is a seperator column where all the columns preceding it will contain identifier data, like VM names, IP addresses, etc.  The columns after it will be used as tag scope.  Preceding the **_SEP_** column, these other columns are required:
      - **ObjectType** Each row's value within this column can be **VM**, **IP**, **SEGMENT**, **TIER0**, **TIER1**, **NETWORK**.  If the row's cell value in the ObjectType column doesn't match any of the accepted values, the entire row will be treated as a comment and ignored.  **NETWORK** types infer that you want to search for NSX overlay segments with IP subnets that fall within the scope specified by **Name**.  
      - **Name** This is the name or sub-string name of the supported objectType.  Matching will be case insensitive.  For **NETWORK** objects, the name must be an IP, CIDR, or range.
      - **Match** The supported values are **startswith**, **endswith**, and **contains**.  Any other value, including blank, will be be treated as an exact case-insensitive match of the **Name**; otherwise, the supported **Match** values are self explainatory; these are also case insensitive.
      - **GroupName** All Groups created by the script will be named with a **SG_** prefix; any groups with **Segment** memberships will have **SG_Segment_** as the prefix.  If provided, the **GroupName** will be appended to the prefix.  If tag values are provided for any of the Scope columns, those will also be appended to the name with each tag seperated by a preceding **_*
      - **Resolve** - This could be **True**, **False** and applies only to ObjectTypes of **IP**, **SEGMENT**, **TIER0**, **TIER1**.  Any value other than **True** will be treated the same way as **False**. If **True**, then the script will solve the provided into into any existing VMs and use those VMs for the Group membership criteria.  For example, for **IP**, the script fill find any VM with an IP address that falls within the provided IP range, IP CIDR, or exact IP.  For **Segment**, **Tier0**, and **Tier1**, the script will resolve to respectively reflect any VMs connected to the matching Segment, any VMs connected to segments under the matching Tier0's downlink entire topology - include any connected Tier1 downlinks, and any VMs connected to the Tier1's downlink topology.  If **False**, the **IP** will be used to create a group with specific IP address set, **Segment** will create groups with Segment memberships, and **TIER0** & **TIER1** will resolve to groups containing all of the segments under the gateway's topology.

  - All columns in the header row after the **_SEP_** column will be used for tag scopes.  Because Each NSX Group definition allows for only up to 5 matching tags, the maximum number of scope columns supported is 5.
    - any row with a cell value under a scope column will result in a tag being created for the matching objects of that row.  
      - The row's tag cell values will also be used to construct the Group's name
      - If the row does not have any tag values for all of the scope columns, then the Group will be created with static memberships for **VM**, **IP** with Resolve=True, **Segments**, **Tier0**, and **Tier1**.  The group name will be the **SG_** or **SG_Segment_** prefix appended with **GroupName**.  If the **GroupName** is empty, then a random UUID will be appended to form the name.
      - For example, if the Scopes are **Site**, **Tenant**, **Environment**, **Application**, a row with tags of Site/SFO, Tenant/HR, Environment/Production, Application/Payroll will result in these groups created where memberships are:
        - SG_SFO - matching all relevant VM or Segment objects with tag Site/SFO
        - SG_SFO_HR - matching all relevant VM or Segment objets with tags Site/SFO and Tenant/HR
        - SG_SFO_HR_Production - matching all relevant VM or Segment objects with tags Site/SFO, Tenant/HR, and Environment/Production
        - SG_SFO_HR_Production_Payroll - matching all relevant VM or Segment objects with tags Site/SFO, Tenant/HR, Environment/Production, and Application/Payroll

    - If a tag value does not exist for one or more of the scopes, then groups won't be created for them.  For example with the above example, if the Production tag does not exist under the Environment scope, then only the Groups SG_SFO, SG_SFO_HR, and SG_SFO_HR_Payroll will be created
    - Due to the way groups are created, the tag definitions should have the widest scope at the left most column and decreasing to the most restrictive scope at the right most column

There's a one special row where a column value is **MultiVMTagScope**.  If provided, any cell value after this column on this row must match one of the Scope names from the header row.  If provided, it means that a relevant object can be tagged more than once iwth that scope.  For example, a VM in the example SG_SFO_HR_Production hierachy could be a database that's shared by the Payroll and Benefits apps.  If the Applicatio scope were to be included in **MultiVMTagScope**, the Application/Payroll and Applicaton/Benefits apps can be added if that VM appears in two differen rows with the required tag values.  If the same object is matched from more than one row with a tag value for a scope that does not appear with **MultiVMTagScope**, then only one tag of that scope will be permited.  For such cases, the most recent tag addition will overwrite the previous one; from the CSV's perspective, the most "recent" is the most bottom entry in the CSV.  For example, if the the Engineering Tenant attempts to tag the same VM with Tenant/Engineering, the VM will lose its "Tenant/HR" tag.  **TBD**: provide option to preserve the oldest one instead.

## How to use the python scripts:
1. You must have a Python environment with the required modules.  If you don't have such an environment, then the NSX Manager root shell meets all the requirements.  I will only test the script on Linux and MacOS with Python3 because these are the ones I've readily available.
2. Copy all the files ending in .py to the same directory on your environment
3. Copy the CSV with the preseed data into the same directory

### grouptag.py syntax
```text
$ python3 grouptag.py --help
usage: grouptag.py [-h] -i INPUT -n NSX [-u USER] [-p PASSWORD] [-l LOGFILE]

options:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        CSV input
  -n NSX, --nsx NSX     NSX Manager
  -u USER, --user USER  NSX user, defaults to admin
  -p PASSWORD, --password PASSWORD
                        NSX user password
  -l LOGFILE, --logfile LOGFILE
```

If a logfile is not provided, logs will be written to logfile.txt on the working directory.
If you do not provide the password paramter, you will be asked for it.  
The JSON output will be printed to the screen, you should redirect it to a file.  example:

```text
$ python3 grouptag.py --nsx jmgr.cptroot.com --input template.csv --user admin > output.json
NSX Manager jmgr.cptroot.com password:

lyd-a01:grouptag lyd$ ls output.json
output.json
```
### grouptagapply.py syntax
```
$ python3 grouptagapply.py -h
usage: grouptagapply.py [-h] -i INPUT -n NSX [-u USER] [-p PASSWORD] [-l LOGFILE] [-g] -m {vm,segment,group,all} [-r] [--rfilter RFILTER] [--trial]

optional arguments:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        JSON file
  -n NSX, --nsx NSX     NSX Manager
  -u USER, --user USER  NSX user, defaults to admin
  -p PASSWORD, --password PASSWORD
                        NSX user password
  -l LOGFILE, --logfile LOGFILE
  -g, --globalmanager   Sent group creation to global manager, --nsx must point to GM, works only with --mode=group
  -m {vm,segment,group,all}, --mode {vm,segment,group,all}
                        vm: tag VMs, segment: tag segments, group: create all groups, all: apply groups, vm tags, segment tags
  -r, --remove          If specified, will delete the configurations pushed from input file
  --rfilter RFILTER     If -r is specified, file containing list of --vms tags, --segment tags, or groups to removed
  --trial               If specified, will not send updates to NSX, just print
```

The input file is the JSON output file from grouptag.py.
If --globalmanager is specified along with the --group option, then groups will be creaed where --nsx is treated as a NSX Federatio Global Manager.  Note that GM's do not have visibility to non-global networks for direct memberships; however, they can create groups matching local segment's via tags.  As such, please ensure that any segment based membership must be tagged based.
You must specify --vm, --segment, or --group.  
  - --vm means to apply all the relevant tags to VMs only
  - --segment means to apply all the relevant tags to Segments only
  - --group means to create all the groups only

If the --remove option is specified, then the script will remove all the tags that have been applied for VM if --vm is also specified or segments if --segment is also specified.  If --group is specified, then the groups will be deleted.  Note, however, that if a group is already being used by other features like firewall rules, then NSX will leave delete option in pending state until the feature that uses it has also been updated to exclude the use of the group.  If the --rfilter is specified, it points to a text file or CSV file where each line of the file or first column of every row points to the name of the group, vm, or segment to apply for the --remmove action.

The script will output all API logs to the specified logfile or logfile.txt.

Both scripts will apppend to the logfile if it already exists.

### TBD 
- I've only tested on the object happy path - meaning I may have to add handlers for cases where a VM may have been deleted in between the running of grouptag.py and grouptagapply.py.
  
    
