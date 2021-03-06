#!/usr/bin/python
# -*- coding: utf-8 -*-

# Using NAT Instances to connect Private instance to internet

import boto3


# Check if the user has the Access & Secret key configured
from boto3 import Session
session = Session()
credentials = session.get_credentials()
current_credentials = credentials.get_frozen_credentials()

# Break & Exit if any of the key is not present
if current_credentials.access_key is None:
    print "Access Key missing, use  `aws configure` to setup"
    exit()

if current_credentials.secret_key is None:
    print "Secret Key missing, use  `aws configure` to setup"
    exit()

globalVars  = {}
globalVars['REGION_NAME']           = "ap-south-1"
globalVars['AZ1']                   = "ap-south-1a"
globalVars['AZ2']                   = "ap-south-1b"
globalVars['CIDRange']              = "10.242.0.0/24"
globalVars['tagName']               = "miztiik-wp-demo-00"
globalVars['EC2-RH-AMI-ID']         = "ami-cdbdd7a2"
globalVars['EC2-Amazon-AMI-ID']     = "ami-3c89f653"
globalVars['EC2-InstanceType']      = "t2.micro"
globalVars['EC2-KeyName']           = "wp-key"

# Creating a VPC, Subnet, and Gateway
ec2         = boto3.resource ( 'ec2', region_name = globalVars['REGION_NAME'] )
ec2Client   = boto3.client   ( 'ec2', region_name = globalVars['REGION_NAME'] )
vpc         = ec2.create_vpc ( CidrBlock = globalVars['CIDRange']  )

# AZ1 Subnets
az1_pvtsubnet   = vpc.create_subnet( CidrBlock = '10.242.0.0/25'   , AvailabilityZone = globalVars['AZ1'] )
az1_pubsubnet   = vpc.create_subnet( CidrBlock = '10.242.0.128/26' , AvailabilityZone = globalVars['AZ1'] )
az1_sparesubnet = vpc.create_subnet( CidrBlock = '10.242.0.192/26' , AvailabilityZone = globalVars['AZ1'] )


# Enable DNS Hostnames in the VPC
vpc.modify_attribute( EnableDnsSupport = { 'Value': True } )
vpc.modify_attribute( EnableDnsHostnames = { 'Value': True } )

# Create the Internet Gatway & Attach to the VPC
intGateway  = ec2.create_internet_gateway()
intGateway.attach_to_vpc( VpcId = vpc.id )

# Create another route table for Public & Private traffic
routeTable = ec2.create_route_table( VpcId = vpc.id )

rtbAssn=[]
rtbAssn.append(routeTable.associate_with_subnet( SubnetId = az1_pubsubnet.id ))
rtbAssn.append(routeTable.associate_with_subnet( SubnetId = az1_pvtsubnet.id ))

# Create a route for internet traffic to flow out
intRoute = ec2Client.create_route( RouteTableId = routeTable.id, 
                                    DestinationCidrBlock = '0.0.0.0/0',
                                    GatewayId = intGateway.id
                                 )

# Tag the resources
tag = vpc.create_tags               ( Tags=[{'Key': globalVars['tagName'] , 'Value':'vpc'}] )
tag = az1_pvtsubnet.create_tags     ( Tags=[{'Key': globalVars['tagName'] , 'Value':'az1-private-subnet'}] )
tag = az1_pubsubnet.create_tags     ( Tags=[{'Key': globalVars['tagName'] , 'Value':'az1-public-subnet'}] )
tag = az1_sparesubnet.create_tags   ( Tags=[{'Key': globalVars['tagName'] , 'Value':'az1-spare-subnet'}] )
tag = intGateway.create_tags        ( Tags=[{'Key': globalVars['tagName'] , 'Value':'igw'}] )
tag = routeTable.create_tags        ( Tags=[{'Key': globalVars['tagName'] , 'Value':'rtb'}] )

# Let create the Public & Private Security Groups
pubSecGrp = ec2.create_security_group( DryRun = False, 
                              GroupName='pubSecGrp',
                              Description='Public_Security_Group',
                              VpcId= vpc.id
                            )

pvtSecGrp = ec2.create_security_group( DryRun = False, 
                              GroupName='pvtSecGrp',
                              Description='Private_Security_Group',
                              VpcId= vpc.id
                            )
pubSecGrp.create_tags(Tags=[{'Key': globalVars['tagName'] ,'Value':'public-security-group'}])
pvtSecGrp.create_tags(Tags=[{'Key': globalVars['tagName'] ,'Value':'private-security-group'}])


# Add a rule that allows inbound SSH, HTTP, HTTPS traffic ( from any source )
ec2Client.authorize_security_group_ingress( GroupId  = pubSecGrp.id ,
                                        IpProtocol= 'tcp',
                                        FromPort=80,
                                        ToPort=80,
                                        CidrIp='0.0.0.0/0'
                                        )
ec2Client.authorize_security_group_ingress( GroupId  = pubSecGrp.id ,
                                        IpProtocol= 'tcp',
                                        FromPort=443,
                                        ToPort=443,
                                        CidrIp='0.0.0.0/0'
                                        )
ec2Client.authorize_security_group_ingress( GroupId  = pubSecGrp.id ,
                                        IpProtocol= 'tcp',
                                        FromPort=22,
                                        ToPort=22,
                                        CidrIp='0.0.0.0/0'
                                        )

# Lets create the key-pair that we will use
### Check if key is already present
customEC2Keys = ec2Client.describe_key_pairs()['KeyPairs']
if not next((key for key in customEC2Keys if key["KeyName"] == globalVars['EC2-KeyName'] ),False):
    ec2_key_pair = ec2.create_key_pair( KeyName = globalVars['EC2-KeyName'] )
    print ("New Private Key created,Save the below key-material\n\n")
    print ( ec2_key_pair.key_material )


# Using the userdata field, we will download, install & configure our basic word press website.
# The user defined code to install Wordpress, WebServer & Configure them
userDataCode = """
#!/bin/bash
set -e -x

# Setting up the HTTP server 
yum install -y httpd php php-mysql mysql
service httpd start
chkconfig httpd on
groupadd www
usermod -a -G www ec2-user


# Download wordpress site & move to http
cd /var/www/
curl -O https://wordpress.org/latest.tar.gz && tar -zxf latest.tar.gz
rm -rf /var/www/html
mv wordpress /var/www/html

# Set the permissions
chown -R root:www /var/www
chmod 2775 /var/www
find /var/www -type d -exec chmod 2775 {} +
find /var/www -type f -exec chmod 0664 {} +

# SE Linux permissive
# needed to make wp connect to DB over newtork
# setsebool -P httpd_can_network_connect=1
# setsebool httpd_can_network_connect_db on

service httpd restart
# Remove below file after testing
echo "<?php phpinfo(); ?>" > /var/www/html/phptestinfo.php
"""

# Create the  Public Word Press Instance
##### **DeviceIndex**:The network interface's position in the attachment order. For example, the first attached network interface has a DeviceIndex of 0 
instanceLst = ec2.create_instances(ImageId = globalVars['EC2-Amazon-AMI-ID'],
                                   MinCount=1,
                                   MaxCount=1,
                                   KeyName=globalVars['EC2-KeyName'] ,
                                   UserData = userDataCode,
                                   InstanceType = globalVars['EC2-InstanceType'],
                                   NetworkInterfaces=[
                                                        {
                                                            'SubnetId': az1_pubsubnet.id,
                                                            'Groups': [ pubSecGrp.id ],
                                                            'DeviceIndex':0,
                                                            'DeleteOnTermination': True,
                                                            'AssociatePublicIpAddress': True,
                                                        }
                                                    ]
                                )

###### Print to Screen ########
print ( "VPC ID                    : {0}".format(vpc.id) )
print ( "AZ1 Public Subnet ID      : {0}".format(az1_pubsubnet.id) )
print ( "AZ1 Private Subnet ID     : {0}".format(az1_pvtsubnet.id) )
print ( "AZ1 Spare Subnet ID       : {0}".format(az1_sparesubnet.id) )
print ( "Internet Gateway ID       : {0}".format(intGateway.id) )
print ( "Route Table ID            : {0}".format(routeTable.id) )
print ( "Public Security Group ID  : {0}".format(pubSecGrp.id) )
print ( "Private Security Group ID : {0}".format(pvtSecGrp.id) )
print ( "EC2 Key Pair              : {0}".format(globalVars['EC2-KeyName']) )
###### Print to Screen ########


"""
Function to clean up all the resources
"""
def cleanAll(resourcesDict=None):

    # Delete the instances
    ids=[]
    for i in instanceLst:
        ids.append(i.id)

    ec2.instances.filter(InstanceIds=ids).terminate()
    
    # Wait for the instance to be terminated
    # Boto waiters might be best, for this demo, i will will "sleep"
    from time import sleep
    sleep(120)

    ec2Client.delete_key_pair( KeyName = globalVars['EC2-KeyName'] )
    
    # Delete Routes & Routing Table
    for assn in rtbAssn:
        ec2Client.disassociate_route_table( AssociationId = assn.id )

    routeTable.delete()

    # Delete Subnets
    az1_pvtsubnet.delete()
    az1_pubsubnet.delete()
    az1_sparesubnet.delete()

    # Detach & Delete internet Gateway
    ec2Client.detach_internet_gateway( InternetGatewayId = intGateway.id , VpcId = vpc.id )
    intGateway.delete()

    # Delete Security Groups
    pubSecGrp.delete()
    pvtSecGrp.delete()

    vpc.delete()
