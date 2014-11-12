function create_vlan(){
  eth_interface=$1
  ib_interface=$2
  current_vlan=$3
  current_mac=$4

  if [ "$current_vlan" == "0" ]; then
    current_vlan=""
    dec_vlan=""
    hex_vlan=""
  else
    shut_down_MSB=$(( ~0x8000 ))
    dec_vlan=$(( $shut_down_MSB & $current_vlan ))
    hex_vlan=".${current_vlan#0x}"
  fi

  ib_create_child_path="/sys/class/net/$ib_interafce/create_child"
  eth_slaves_path="/sys/class/net/$eth_interface/eth/slaves"
  eth_vifs_path="/sys/class/net/$eth_interface/eth/vifs"

  echo "$current_vlan.1"  > $ib_create_child_path && \
  ifconfig $eth_interface up && \
  echo "+$ib_interafce$hex_vlan.1"  > $eth_slaves_path && \
  echo "+$ib_interafce$hex_vlan.1" $current_mac $dec_vlan  > $eth_vifs_path

}

# Read mapping lines of the form "eth0 over IB port: ib0"
while read -r line
do
  line_arr=( $line )
  eth_interface=${line_arr[0]}
  ib_interafce=${line_arr[4]}
  current_mac=`ip link show $eth_interface | grep link | awk '{print $2}'`

  # Create default VLAN
  vlan="0"
  create_vlan $eth_interface $ib_interafce $vlan $current_mac

  # Create SM VLANs
  port_to_dev=( `ibdev2netdev |grep " $ib_interafce "` )
  device=${port_to_dev[0]}
  port=${port_to_dev[2]}
  sm_vlans=`cat /sys/class/infiniband/$device/ports/$port/pkeys/* | grep -v 0xffff | grep -v 0x7fff | grep -v 0000`
  for vlan in $sm_vlans;
  do
    create_vlan $eth_interface $ib_interafce $vlan $current_mac
    sleep 0.5
  done

done < "/sys/class/net/eth_ipoib_interfaces"
