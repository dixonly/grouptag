#/usr/bin/env python3
import sys
import csv
import argparse
from nsxconnect import NsxConnect
import getpass
import ipaddress
import uuid
import copy
from logger import Logger


class Tag():
    def __init__(self):
        self.tags = []

    def update(self, taglist, tags=None):
        if not isinstance(tags, list):
            tags=self.tags
        for tag in taglist:
            if tag not in tags:
                tags.append(tag)
        return tags
    
    def remove(self, taglist, tags=None):
        if not tags:
            tags=self.tags
            tags = [tag for tag in tags if tag not in taglist]
        return tags
        
    def create(self, value, scope=None):
        if scope:
            return {"scope": scope, "tag": value}
        else:
            return {"tag": value}

    def getTags(self):
        return self.tags

        
def parseParameters():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True, help="CSV input")
    parser.add_argument("-n", "--nsx", required=True, help="NSX Manager")
    parser.add_argument("-u", "--user", required=False, default="admmin",
                        help="NSX user, defaults to admin")
    parser.add_argument("-p", "--password", required=False,
                        help="NSX user password")
    parser.add_argument("-l", "--logfile", required=False, default="logfile.txt")
    
    args = parser.parse_args()
    return args



def getAllVms(nsx):
    vms = nsx.get(api="/policy/api/v1/infra/realized-state/virtual-machines",
                  codes=[200], verbose=False,display=False)
    return vms

def getAllVifs(nsx):
    vifs = nsx.get(api="/api/v1/fabric/vifs",
                  codes=[200], verbose=False,display=False)
    return vifs


def findNsxNetwork(nsx, objectType, logger, operator, name=None):
    # operator can be startswith, endswith, contains, else match
    if objectType.lower() not in ["segment", "tier1", "tier0"]:
        logger.log(logger.WARN, "findNsxNetwork: unsupported type: "%objectType)
        return []
    objs = nsx.get(api="/policy/api/v1/search/query?query=resource_type:%s" %objectType,
                   verbose=False)
    found =[]
    if name:
        for o in objs["results"]:
            if operator=="startswith":
                
                if o["display_name"].strip().lower().startswith(name.strip().lower()):
                    found.append(o)
            elif operator=="endswith":
                if o["display_name"].strip().lower().endswith(name.strip().lower()):
                    found.append(o)
            elif operator=="contains":
                if name.strip().lower() in o["display_name"].strip().lower():
                    found.append(o)
            else:
                if o["display_name"].strip().lower() == name.strip().lower():
                    found.append(o)
                    break
        return found
    else:
        return objs["results"]

    return []
                
def findSegmentAttachedVMs(nsx, segments, vms, logger):
    vmlist=[]
    for segment in segments:
        ports = nsx.get(api="/policy/api/v1%s/ports" % segment["path"], verbose=False)
            
        for port in ports["results"]:
            if not "attachment" in port:
                continue
            for vm in vms:
                found=False
                if not "attachments" in vm:
                    continue
                for a in vm["attachments"]:
                    if not "lport_attachment_id" in a:
                        continue
                    if a["lport_attachment_id"] == port["attachment"]["id"]:
                        vmlist.append(vm)
                        found=True
                        break
                if found:
                    break
    return vmlist
        
def associateVifsToVms(vms, vifs, logger, progress=True):
    '''
    Given list of VIFs and VMs, find each VIF's VM and update
    the VM with the VIF attachment
    '''
    if progress:
        logger.log(logger.INFO, "Associating %d VIFs to %d VMs" %(len(vifs), len(vms)))
    count = 0
    for vif in vifs:
        count+=1
        if progress and count % 100 == 0:
            logger.log(logger.INFO, "  Processed %d of %d VIFs" %(count, len(vifs)))
        found=False
        for vm in vms:
            if vif["owner_vm_id"] == vm["external_id"]:
                if "attachments" in vm.keys():
                    vm["attachments"].append(vif)
                else:
                    vm["attachments"] = [vif]
                found=True
                break
        if not found:
            logger.log(logger.WARN, "VIF %d on VM UUID %d not found" %
                  (vif["external_id"], vif["owner_vm_id"]))

def findHeaderIndex(header, sep, logger):
    try:
        return header.index(sep) 
    except ValueError:
        logger.log(logger.ERROR, "Header row from CSV has no seperator column labeled as '%s'" %sep)
        exit()

def findOneVM(vms, name, ignorecase=True):
    if ignorecase:
        name=name.lower()
    for vm in vms:
        if vm["display_name"].lower() == name:
            return [vm]
    return []

def findVMContains(vms, name, ignorecase=True):
    if ignorecase:
        namelower=name.lower()
    found = []
    for vm in vms:
        if ignorecase:
            if namelower in vm["display_name"].lower():
                found.append(vm)
        else:
            if name in vm["display_name"]:
                found.append(vm)
    return found

def findVMsStartsWith(vms, name, ignorecase=True):
    if ignorecase:
        namelower=name.lower()
    found = []
    for vm in vms:
        if ignorecase:
            if vm["display_name"].lower().startswith(namelower):
                found.append(vm)
        else:
            if vm["display_name"].startswith(name):
                found.append(vm)
    return found

def findVMsEndsWith(vms, name, ignorecase=True):
    if ignorecase:
        namelower=name.lower()
    found = []
    for vm in vms:
        if ignorecase:
            if vm["display_name"].lower().endswith(namelower):
                found.append(vm)
        else:
            if vm["display_name"].endswith(name):
                found.append(vm)
    return found
        
def findVMsFromName(vms, name, matchtype):
    name=name.strip()
    matchtype = matchtype.strip().lower()

    if matchtype == 'contains':
        return findVMContains(vms, name)
    elif matchtype == 'endswith':
        return findVMsEndsWith(vms, name)
    elif matchtype == 'startswith':
        return findVMsStartsWith(vms, name)
    else:
        return findOneVM(vms, name)
    return []

def createExpressionFromTags(tags, mtype, logger, conjunction="AND"):
    first=True
    expressions = []
    count = 0
    for tag in tags:
        if not first:
            expr = {}
            expr["resource_type"] = "ConjunctionOperator"
            expr["conjunction_operator"] = conjunction
            expressions.append(expr)
        expr = {}
        expr["resource_type"] = "Condition"
        expr["key"] = "Tag"
        expr["member_type"] = mtype
        expr["operator"] = "EQUALS"
        expr["value"] = "%s|%s" %(tag["scope"], tag["tag"])
        expressions.append(expr)
        count+=1
        first=False
    if count > 5:
        logger.log(logger.ERROR, "Number of tags expressions exceed 5")
        exit(0)

    return expressions

def updateSegments(segmentlist, segment, logger):
    T = Tag()
    for s in segmentlist:
        if s["url"] == segment["url"]:
            s["payload"]["tags"] = T.update(taglist=s["payload"]["tags"],
                                            tags=segment["payload"]["tags"])
            # found match, return
            return segmentlist

    #no match if this point reached
    segmentlist.append(segment)
    return segmentlist

def updateVMs(vmlist, vm, logger):
    T = Tag()
    for v in vmlist:
        if v["url"] == vm["url"]:
            v["payload"]["tags"] = T.update(taglist=v["payload"]["tags"],
                                            tags=vm["payload"]["tags"])
            # found match, return
            return vmlist

    #no match if this point reached
    vmlist.append(vm)
    return vmlist
        
    
def updateGroups(groups, newconfig, logger):
    # groups - list of all existing groups
    # newgroup - proposed new group
    # determine if the definition of newgroup already exists as member of previously defined groups
    #   if not member, add to and return the new groups, otherwise, return groups

    # for this specifically, there should only be maximum of three non-conjunction expressions:
    #     ipset, segmentpaths, nested tag list
    for group in groups:
        grp = group["payload"]
        newgroup = newconfig["payload"]
        if len(grp["expression"]) != len(newgroup["expression"]):
            continue
        match=False
        for i in range(0,len(grp["expression"])):
            if i%2 == 1:
                # conjunctions are odd and we only create "OR" at first level
                continue
            else:
                old=grp["expression"][i]
                
            for n in range(0, len(newgroup["expression"])):
                if n%2 == 1:
                    continue
                else:
                    newg = newgroup["expression"][n]
                    
                if old["resource_type"] != newg["resource_type"]:
                    continue
                if old["resource_type"] == "IPAddressExpression":
                    if sorted(old["ip_addresses"]) == sorted(newg["ip_addresses"]):
                        match = True
                elif old["resource_type"] == "PathExpression":
                    if sorted(old["paths"]) == sorted(newg["paths"]):
                        match = True
                elif old["resource_type"] == "NestedExpression":
                    if compareTagExpressions(old["expressions"], newg["expressions"]):
                        match = True
                elif old["resource_type"] == "Condition":
                    if old==newg:
                        match = True
                else:
                    logger.log(logger.ERROR,
                               "Unexpected group type: %s"
                               % old)
                    exit(0)
                if not match:
                    break
            if not match:
                break
        if match:
            # all the expressions match
            return groups
    # by this point, it means no match has been found
    groups.append(newconfig)
    return groups
                    
def createSegmentGroup(nsx, segments, row, header, logger, output):
    sgNameIndex = findHeaderIndex(header=header, sep="GroupName", logger=logger)
    scopeIndex = findHeaderIndex(header=header, sep="_SEP_", logger=logger) + 1
    tags=[]
    T = Tag()
    tagged = False
    apis=[]

    for t in range(scopeIndex, len(header)):
        if not row[t]:
            continue
        tag = T.create(scope=header[t], value=row[t])
        tags = T.update(taglist=[tag], tags=tags)
        tagged = True

    if not tagged:
        group={}
        if row[sgNameIndex]:
            group["display_name"] = "SG_Segment_%s" %row[sgNameIndex]
        else:
            group["display_name"] = "SG_Segment_%s" %uuid.uuid4()
        group["expression"] = []
        expr={}
        expr["resource_type"] = "PathExpression"
        expr["paths"] = []
        for segment in segments:
            expr["paths"].append(segment["path"])
        if not row[sgNameIndex]:
            group["display_name"] = "SG_Segment_%s" % uuid.uuid4()
        else:
            group["display_name"] = "SG_Segment_%s" % row[sgNameIndex]
        group["expression"].append(expr)
        groupapi={}
        groupapi["url"] = "/policy/api/v1/infra/domains/default/groups/%s" % group["display_name"]
        groupapi["payload"] = group
        groupapi["method"] = "patch"
        groupapi["type"] = "group"
        groupapi["search"] = row
        apis.append(groupapi)

    else:
        for i in range(1,len(tags)+1):
            group={}
            expr={}
            expressions = createExpressionFromTags(tags=tags[:i], mtype="Segment",
                                                           logger=logger)
            if len(expressions) <= 1:
                expr["resource_type"] = "Condition"
                group["expression"] = expressions
            else:
                expr["resource_type"] = "NestedExpression"
                expr["expressions"] = expressions
                group["expression"] = [expr]                
            if row[sgNameIndex]:
                group["display_name"] = "SG_Segment_%s" %row[sgNameIndex]
            else:
                group["display_name"] = "SG_Segment"
            for t in tags[:i]:
                group["display_name"] += "_%s" %t["tag"]


            groupapi={}
            groupapi["url"] = "/policy/api/v1/infra/domains/default/groups/%s" % group["display_name"]
            groupapi["payload"] = group
            groupapi["method"] = "patch"
            groupapi["type"] = "group"
            groupapi["search"] = row
            apis.append(groupapi)

    if tagged:
        for segment in segments:
            # have to re-do GET api because the query searches for all segments with
            # return payloads that have consolidated status, and may not be complete
            # this now gets the complete object
            realSegment=nsx.get(api="/policy/api/v1%s" %segment["path"], codes=[200],
                                verbose=False, display=False)
            if not "tags" in realSegment:
                realSegment["tags"] = []
            newtags = copy.deepcopy(realSegment["tags"])
            newtags = T.update(taglist=tags, tags=newtags)
            segmentapi={}
            segmentapi["url"] = "/policy/api/v1%s" % realSegment["path"]
            segmentapi["original_tags"] = realSegment["tags"]
            realSegment["tags"] = newtags
            segmentapi["payload"] = realSegment
            segmentapi["method"] = "patch"
            segmentapi["type"] = "segment"
            segmentapi["search"] = row
            apis.append(segmentapi)

    return apis

def createVMGroup(row, vmlist, header, logger, output):
    sgNameIndex = findHeaderIndex(header=header, sep="GroupName", logger=logger)
    scopeIndex = findHeaderIndex(header=header, sep="_SEP_", logger=logger) + 1
    T = Tag()
    apis = []
    tags=[]
    for i in range(scopeIndex, len(header)):
        if not row[i]:
            continue
        tag = T.create(scope=header[i], value=row[i])
        tags = T.update(taglist=[tag], tags=tags)

        
    for i in range(1,len(tags)+1):
        group={}
        expr = {}
        if row[sgNameIndex]:
            group["display_name"] = "SG_%s" %row[sgNameIndex]
        else:
            group["display_name"] = "SG"
        for t in tags[:i]:
            group["display_name"] += "_%s" % t["tag"]
        
        expressions = createExpressionFromTags(tags=tags[:i],
                                                       mtype="VirtualMachine",
                                                       logger=logger)
        if len(expressions) <= 1:
            expr["resource_type"] = "Condition"
            group["expression"] = expressions
        else:
            expr["resource_type"] = "NestedExpression"
            expr["expressions"] = expressions
            group["expression"] = [expr]
        groupapi={}
        groupapi["url"] = "/policy/api/v1/infra/domains/default/groups/%s" %group["display_name"]
        groupapi["payload"] = group
        groupapi["method"] = "patch"
        groupapi["type"] = "group"
        groupapi["search"] = row
        apis.append(groupapi)
    
    if len(tags) == 0 and len(vmlist) > 0:
        group = {}
        if row[sgNameIndex]:
            group["display_name"] = "SG_VM_%s" %row[sgNameIndex]
        else:
            group["display_name"] = "SG_VM_%s" %uuid.uuid4()
        expr = {}
        expr["resource_type"] = "ExternalIDExpression"
        expr["member_type"] = "VirtualMachine"
        expr["external_ids"] = []
        for vm in vmlist:
            expr["external_ids"].append(vm["external_id"])
        group["expression"] = [expr]
        groupapi={}
        groupapi["url"] = "/policy/api/v1/infra/domains/default/groups/%s" % group["display_name"]
        groupapi["payload"] = group
        groupapi["method"] = "patch"
        groupapi["type"]= "group"
        groupapi["search"] = row
        apis.append(groupapi)

    if len(tags) > 0:
        for vm in vmlist:
            ntags = []
            for tag in tags:
                ind = output["scopeheader"].index(tag["scope"])
                if "tags" not in vm.keys():
                    vm["tags"] = []

                
                if output["scopes"][ind]["value"] != tag["scope"]:
                    logger.error("Output scope index has %s instead of %s" %(s["value"],
                                                                             tag["scope"]))
                multitag = output["scopes"][ind]["multitag"]
                found=False
                for s in output["scopes"][ind]["tags"]:
                    if tag==s["tag"]:
                        if vm["external_id"] not in s["apply_to"][0]["resource_ids"]:
                            if tag in vm["tags"]:
                                logger.info("*Not adding tag %s to vm %s because it already has original list:%s" %(tag, vm["display_name"], vm["tags"]))
                                continue
                            s["apply_to"][0]["resource_ids"].append(vm["external_id"])
                            output["scopes"][ind]["tagsremove"][output["scopes"][ind]["tags"].index(s)]["remove_from"][0]["resource_ids"].append(vm["external_id"])
                            found = True
                    elif not multitag:
                        if vm["external_id"] in s["apply_to"][0]["resource_ids"]:
                            logger.warn("VM %s with ID %s being removed from %s by adding to %s because scope %s is not multitag allowed." %(vm["display_name"], vm["external_id"], s["tag"], tag, tag["scope"]))
                            s["apply_to"][0]["resource_ids"].remove(vm["external_id"])

                            
                if not found:
                    if tag in vm["tags"]:
                        logger.info("Not adding tag %s to vm %s because it already has original tags list:%s" %(tag, vm["display_name"],vm["tags"]))
                        
                    else:
                        checkmulti=False
                        if not multitag:
                            for otag in vm["tags"]:
                                if otag["scope"] == tag["scope"]:
                                    checkmulti=True
                                    logger.info("Not adding tag %s to VM %s because it already has non-multitag scope allowed tag: %s" %(tag, vm["display_name"], vm["tags"]))
                                    break
                        if not checkmulti:
                            newtag = {}
                            newtag["tag"] = copy.deepcopy(tag)
                            newtag["apply_to"] = [{"resource_type": "VirtualMachine",
                                                   "resource_ids": [vm["external_id"]]}]
                            output["scopes"][ind]["tags"].append(newtag)
                            rtag={}
                            rtag["tag"] = newtag["tag"]
                            rtag["remove_from"] = [{"resource_type": "VirtualMachine",
                                                    "resource_ids": [vm["external_id"]]}]
                            output["scopes"][ind]["tagsremove"].append(rtag)
            
    return apis
        

def createIPGroup(nsx, name, ips, logger):
    group={}
    group["expression"]=[]
    data={}
    data["resource_type"] = "IPAddressExpression"
    data["ip_addresses"] = []
    for ip in ips:
        if ip["type"] =="CIDR":
            data["ip_addresses"].append(str(ip["cidr"]))
        elif ip["type"] == "IP":
            data["ip_addresses"].append(str(ip["ip"]))
        elif ip["type"] == "RANGE":
            data["ip_addresses"].append("%s-%s" %(ip["first"], ip["second"]))
        else:
            logger.log(logger.ERROR, "createIPGroup() ERROR: unexpected IP type - %s" %ip)
            exit()
    group["expression"].append(data)
    if not name:
        name="SG_IPSET_%s" % uuid.uuid4()
    else:
        name="SG_IPSET_%s" %name
    group["display_name"] = name
        
    api={}
    api['url'] = "/policy/api/v1/infra/domains/default/groups/%s" %name
    api['payload'] = group
    api['method'] = "patch"
    api["type"] = "group"
    return [api]

def validateIP(inputstr, logger):
    # allow comma seprated list
    iplist=[]
    inputstr = inputstr.split(",")
    for i in inputstr:
        ipdata = {}
        if '-' in i:
            iprange = i.split('-')
            if len(iprange) != 2:
                logger.log(logger.ERROR,
                           "Dash '-' in input %s, there must be only one dash separating two IP addresses" % i)
                exit()
            if '/' in iprange[0] or '/' in iprange[1]:
                logger.log(logger.ERROR,
                           "Input IP range %s must not specify element with mask seperator '/'"
                      %i)
                exit()

            try:
                first = ipaddress.ip_address(iprange[0].strip())
                second = ipaddress.ip_address(iprange[1].strip())
            except ValueError as e:
                logger.log(logger.ERROR,"IP range %s has error:  %s" %(i, e))
                exit()
            if first >second:
                logger.log(logger.ERROR, "IP %s in range %s is smaller than %s" %(first, i, second))
                exit()
            ipdata['type'] = "RANGE"
            ipdata['first'] = first
            ipdata['second'] = second
            iplist.append(ipdata)
            
        elif '/' in i:
            try:
                cidr = ipaddress.ip_network(i.strip())
            except ValueError as e:
                logger.log(logger.ERROR, "IP subnet input error: %s" %e)
                exit()

            ipdata['type'] = "CIDR"
            ipdata['cidr'] = cidr
            iplist.append(ipdata)
        else:
            try:
                ip = ipaddress.ip_address(i)
            except ValueError as e:
                logger.log(logger.ERROR, "Input %s error: %s" %(i, e))
                exit()
            ipdata['type'] = "IP"
            ipdata["ip"] = ip
            iplist.append(ipdata)
                
    return iplist

def findVMsWithIP(vmlist, iplist, logger):
    vms=[]
    for ip in iplist:
        if ip["type"] == "RANGE":
            for vm in vmlist:
                matched=False
                if not "attachments" in vm:
                    continue
                for vif in vm["attachments"]:
                    for addrinfo in vif["ip_address_info"]:
                        if not "ip_addresses" in addrinfo:
                            break
                        for addr in addrinfo["ip_addresses"]:
                            iptmp = ipaddress.ip_address(addr)
                            if iptmp.is_loopback:
                                continue
                            if iptmp.version != ip["first"].version:
                                continue
                            if iptmp >= ip["first"] and iptmp <= ip["second"]:
                                matched=True
                                vms.append(vm)
                                #addr loop
                                break
                            
                        if matched:
                            # attachments  loop
                            break
                    if matched:
                        # vif loop
                        break
        elif ip["type"] == "CIDR":
            for vm in vmlist:
                matched=False
                if not "attachments" in vm:
                    continue
                for vif in vm["attachments"]:
                    for addrinfo in vif["ip_address_info"]:
                        if not "ip_addresses" in addrinfo:
                            break
                        for addr in addrinfo["ip_addresses"]:
                            iptmp = ipaddress.ip_address(addr)
                            if iptmp.is_loopback:
                                continue
                            if iptmp.version != ip["cidr"].version:
                                continue
                            if iptmp in ip["cidr"].hosts():
                                matched=True
                                vms.append(vm)
                                break
                        if matched:
                            # attachments  loop
                            break
                    if matched:
                        # vif loop
                        break
        elif ip["type"] == "IP":
            for vm in vmlist:
                matched=False
                if not "attachments" in vm:
                    continue
                for vif in vm["attachments"]:
                    for addrinfo in vif["ip_address_info"]:
                        if not "ip_addresses" in addrinfo:
                            break
                        for addr in addrinfo["ip_addresses"]:
                            iptmp = ipaddress.ip_address(addr)
                            if iptmp.is_loopback:
                                continue
                            if iptmp.version != ip["ip"].version:
                                continue
                            if iptmp == ip["ip"]:
                                matched=True
                                vms.append(vm)
                                break
                        if matched:
                            # attachments  loop
                            break
                    if matched:
                        # vif loop
                        break

    return vms
def compareTagExpressions(src, dst):
    oldlist=[]
    newlist=[]
    for i in src:
        if i["resource_type"] != "ConjunctionOperator":
            oldlist.append(i)
    for i in dst:
        if i["resource_type"] != "ConjunctionOperator":
            newlist.append(i)
    if sorted(oldlist, key=lambda x: x["value"]) == sorted(newlist, key = lambda y: y["value"]):
        return True
    else:
        return False

                            
def associateGroups(nsx, header, multitag, data, vms, logger):
    scopeIndex = findHeaderIndex(header=header, sep="_SEP_", logger=logger) + 1
    nameIndex = findHeaderIndex(header=header, sep="Name", logger=logger)
    matchIndex = findHeaderIndex(header=header, sep="Match", logger=logger)
    resolveIndex = findHeaderIndex(header=header, sep="Resolve", logger=logger)
    sgNameIndex = findHeaderIndex(header=header, sep="GroupName", logger=logger)
    objIndex = findHeaderIndex(header=header, sep="ObjectType", logger=logger)

    output={}
    output["groups"] = []
    output["vms"] = []
    output["segments"] = []
    output["vmscopes"] = []
    output["scopeheader"] = []
    output["scopes"] = []
    for i in range(scopeIndex, len(header)):
        scope={}
        scope["value"] = header[i].strip()
        if scope["value"] in multitag:
            scope["multitag"] = True
        else:
            scope["multitag"] = False

        scope["tags"] = []
        scope["tagsremove"] = []
        output["scopes"].append(scope)
        output["scopeheader"].append(scope["value"])
        # here we expect scope["tags] to be a dictionary of NSX TagBulkOperation
        #  
        #  { "tag": tag,
        #     "apply_to": [{"resource_type": "VirtualMachine", "resource_ids": []}]
        #  }
        #
        # scope["tagremove"] would contain the opposite where we want to remove
        # all the new tags that we've added to the VM
        #  { "tag": tag,
        #     "remove_from": [{"resource_type": "VirtualMachine", "resource_ids": []}]
        #  }

        
    T = Tag()
    for row in data:
        vmlist = []
        resolve=True
        newgroup=[]
        segments=[]
        if row[objIndex].strip().lower() == "ip":
            ips = validateIP(row[nameIndex], logger)
            if len(ips) == 0:
                logger.log(logger.ERROR,
                           ("IP specifier %s resulted in no valid IPs" % row(nameIndex)))
                exit()
            if row[resolveIndex].strip().lower() == 'true':
                vmlist = findVMsWithIP(vms, ips, logger)
            else:
                resolve=False
                newgroup = createIPGroup(nsx=nsx, name=row[sgNameIndex],
                                            ips=ips, logger=logger)
        elif row[objIndex].strip().lower() == "vm":
            vmlist = findVMsFromName(vms, row[nameIndex], row[matchIndex])
        else:
            if row[objIndex].strip().lower() not in ["segment", "tier0", "tier1"]:
                logger.log(logger.ERROR, "Don't have handler for type %s" %row[objIndex])
                exit()
            if row[objIndex].strip().lower() == "segment":
                segments.extend(findNsxNetwork(nsx=nsx, objectType="segment",
                                          logger=logger,
                                          operator=row[matchIndex].strip().lower(),
                                          name=row[nameIndex].strip()))
            else:
                gw = findNsxNetwork(nsx=nsx, objectType=row[objIndex].strip().lower(),
                                    operator=row[matchIndex].strip().lower(),
                                    name=row[nameIndex].strip(),
                                    logger=logger)
                if not gw:
                    logger.log(logger.WARN, "Gateway %s not found" %row[nameIndex])
                    continue
                else:
                    gw=gw[0]

                allsegments = findNsxNetwork(nsx=nsx, objectType="segment",
                                             operator=row[matchIndex].strip().lower(),
                                             name=None, logger=logger)
                for segment in allsegments:
                    if "connectivity_path" not in segment:
                        continue
                    
                    if segment["connectivity_path"] == gw["path"]:
                        segments.append(segment)

                if gw["resource_type"] == "Tier0":
                    tier1s = findNsxNetwork(nsx=nsx, objectType="tier1", name=None,
                                            logger=logger,
                                            operator=row[matchIndex].strip().lower())
                    for t1 in tier1s:
                        if "tier0_path" in t1 and t1["tier0_path"] == gw["path"]:
                            for segment in allsegments:
                                if "connectivity_path" not in segment:
                                    continue
                                if segment["connectivity_path"] == t1["path"]:
                                    segments.append(segment)


            if row[resolveIndex].strip().lower() == "true":
                vmlist = findSegmentAttachedVMs(nsx, segments, vms, logger)
            else:
                resolve=False
                newgroup = createSegmentGroup(nsx=nsx, segments=segments, row=row,
                                              header=header, output=output,
                                              logger=logger)

        #logger.info("Input: %s, vm matches: %d segmentmatches: %d, resolve: %s"
        #           %(row[nameIndex], len(vmlist), len(segments), row[resolveIndex]))
        if vmlist:
            newgroup.extend(createVMGroup(row, vmlist, header, logger, output))
        
        if newgroup:
            for i in newgroup:
                if i["type"] == "group":
                    for e in i["payload"]["expression"]:
                        if e["resource_type"] == "NestedExpression" and len(e["expressions"]) == 0:
                            logger.log(logger.INFO, "newgroup: %s" %i)
                            logger.log(logger.ERROR, "no tags: %s" % row)
                    output["groups"] = updateGroups(output["groups"], i, logger)
                elif i["type"] == "segment":
                    output["segments"] = updateSegments(output["segments"], i, logger)
                elif i["type"] == "vm":
                    output["vms"] = updateVMs(output["vms"], i, logger)

    nsx.jsonPrint(output, stdout=True)
def main():
    args = parseParameters()
    logger = Logger(args.logfile)
    if not args.password:
        args.password = getpass.getpass("NSX Manager %s password: " %args.nsx)
    with open(args.input, 'r', newline='') as fp:
        csvreader = csv.reader(fp)
        data = [row for row in csvreader]
        fp.close()

    vmRows = []
    header=None
    multitag=[]
    for row in data:
        if "ObjectType" in row:
            header=row
            objIndex=findHeaderIndex(header=header, sep="ObjectType", logger=logger)
        if "MultiVMTagScope" in row:
            multitag=row
            i = multitag.index("MultiVMTagScope")
            for m in range(i+1, len(multitag)):
                multitag[m] = multitag[m].strip()
            logger.info("multitags: %s" %multitag)
        if not header:
            continue
        if row[objIndex].strip().lower() in ["vm", "ip", "segment", "tier0", "tier1"]:
            vmRows.append(row)
    if not header:
        logger.log(logger.ERROR, "No header row found in CSV")
        return

    nsx = NsxConnect(server=args.nsx, user=args.user,
                     password=args.password, logger=logger)
    nsxVms = getAllVms(nsx)
    nsxVifs = getAllVifs(nsx)
    associateVifsToVms(nsxVms["results"], nsxVifs["results"], logger)
    
    for vm in nsxVms["results"]:
        #nsx.jsonPrint(vm)
        pass
        
    # header[3] is first tag scope
    groups=associateGroups(nsx, header, multitag, vmRows, nsxVms['results'], logger)
    
if __name__ == "__main__":
    main()
